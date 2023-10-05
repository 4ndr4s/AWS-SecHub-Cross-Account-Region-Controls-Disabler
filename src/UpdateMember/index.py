#!/bin/python

import logging
import os, json, sys
import time
from typing import List, Dict
import boto3
import botocore

from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.basicConfig(stream=sys.stdout, level=logging.INFO)


def get_enabled_standard_subscriptions(standards, account_id, security_hub_client, region):
    """ return enabled standard in account_id """
    standards_subscription_arns_plain = [
        arn["StandardsArn"] for arn in standards["Standards"]
    ]
    standards_subscription_arns = [
        arn.replace(":::", "::" + account_id + ":").replace(
            ":" + region + "::",
            ":" + region + ":" + account_id + ":",
        )
        for arn in standards_subscription_arns_plain
    ]
    enabled_standards = security_hub_client.get_enabled_standards(
        StandardsSubscriptionArns=standards_subscription_arns
    )
    return enabled_standards


def get_controls(enabled_standards, security_hub_client):
    """ return list of controls for all enabled standards """
    controls = dict()
    for standard in enabled_standards["StandardsSubscriptions"]:
        response = security_hub_client.list_security_control_definitions(
            StandardsArn=standard["StandardsArn"])
        controls[standard["StandardsArn"]] = response["SecurityControlDefinitions"]
        while "NextToken" in response:
            next_token = response["NextToken"]
            response = security_hub_client.list_security_control_definitions(
                StandardsArn=standard["StandardsArn"], NextToken=next_token)
            controls[standard["StandardsArn"]] = controls[standard["StandardsArn"]] + response["SecurityControlDefinitions"]
    removed_items = []
    for key, value in controls.items():
        control_items = [item['SecurityControlId'] for item in value if item.get('CurrentRegionAvailability') != 'UNAVAILABLE']
        removed_items.extend([item['SecurityControlId'] for item in value if item.get('CurrentRegionAvailability') == 'UNAVAILABLE'])
        controls[key] = control_items
    logger.info("controls not available: %s for standards: %s", removed_items, enabled_standards['StandardsSubscriptions'])
    return controls


class SecurityStandardUpdateError(Exception):
    """ Error Class for failed security standard subscription update """

    pass


sts_client = None
DISABLED_REASON = "Control disabled because control in DDB but not reason provided."
DISABLED = "DISABLED"
ENABLED = "ENABLED"
dynamodb_client = None


def get_control_status(standard_control_association, member_security_hub_client):
    response = member_security_hub_client.batch_get_standards_control_associations(
        StandardsControlAssociationIds=standard_control_association)
    return response['StandardsControlAssociationDetails']


def update_member(controls, security_hub_client, exceptions):
    """
    Identifying which control needs to be updated
    """
    standard_control_association = []
    control_count = 0
    control_status = []
    for admin_key in controls:
        for control in controls[admin_key]:
            control_count += 1
            standard_control_association.append({'StandardsArn': admin_key, 'SecurityControlId': control})
            if control_count == 100:
                control_status.extend(get_control_status(standard_control_association, security_hub_client))
                standard_control_association = []
                control_count = 0
    control_status.extend(get_control_status(standard_control_association, security_hub_client))
    for control in control_status:
        if control['SecurityControlId'] in exceptions["Disabled"]:
            if control['AssociationStatus'] != DISABLED:
                logger.info(" %s control will be disabled in %s", control['SecurityControlId'], control['StandardsArn'])
                # Disable control in target account
                update_control_status(
                    control['StandardsArn'], control['SecurityControlId'],
                    security_hub_client,
                    DISABLED,
                    disabled_reason=exceptions["DisabledReason"][
                        control["SecurityControlId"]
                    ],
                )
        elif control['SecurityControlId'] in exceptions["Enabled"]:
            if control['AssociationStatus'] != ENABLED:
                # Enable control in member account
                logger.info(" %s control will be enabled in %s", control['SecurityControlId'], control['StandardsArn'])
                update_control_status(
                    control['StandardsArn'], control['SecurityControlId'],
                    security_hub_client,
                    ENABLED
                )
        elif control['AssociationStatus'] != ENABLED:
            # Enable control in member account
            logger.info(" %s control not in DDB and disabled in %s", control['SecurityControlId'], control['StandardsArn'])
            update_control_status(
                control['StandardsArn'], control['SecurityControlId'],
                security_hub_client,
                ENABLED
            )


def update_control_status(standard_control, control_id, client, new_status, disabled_reason=None):
    """
    Updates the Security Hub control as specified in the the security hub administrator account
    """
    if DISABLED == new_status:
        client.batch_update_standards_control_associations(
            StandardsControlAssociationUpdates=[
                {
                    'StandardsArn': standard_control,
                    'SecurityControlId': control_id,
                    'AssociationStatus': new_status,
                    'UpdatedReason': disabled_reason if disabled_reason else DISABLED_REASON
                }
            ]
        )
    else:
        # ENABLE control
        client.batch_update_standards_control_associations(
            StandardsControlAssociationUpdates=[
                {
                    'StandardsArn': standard_control,
                    'SecurityControlId': control_id,
                    'AssociationStatus': new_status
                }
            ]
        )


def update_standard_subscription(administrator_enabled_standards, member_enabled_standards, client):
    """
    Update security standards to reflect state in administrator account
    """
    admin_standard_arns = [
        standard["StandardsArn"]
        for standard in administrator_enabled_standards["StandardsSubscriptions"]
    ]
    member_standard_arns = [
        standard["StandardsArn"]
        for standard in member_enabled_standards["StandardsSubscriptions"]
    ]
    standards = client.describe_standards()["Standards"]
    standard_to_be_enabled = []
    standard_to_be_disabled = []

    for standard in standards:
        if (
            standard["StandardsArn"] in admin_standard_arns
            and standard["StandardsArn"] not in member_standard_arns
        ):
            # enable standard
            standard_to_be_enabled.append({"StandardsArn": standard["StandardsArn"]})
        if (
            standard["StandardsArn"] not in admin_standard_arns
            and standard["StandardsArn"] in member_standard_arns
        ):
            # disable standard
            for subscription in member_enabled_standards["StandardsSubscriptions"]:
                if (
                    subscription["StandardsArn"].split("/")[-3]
                    == standard["StandardsArn"].split("/")[-3]
                ):
                    standard_to_be_disabled.append(
                        subscription["StandardsSubscriptionArn"]
                    )

    standards_changed = False

    if len(standard_to_be_enabled) > 0:
        # enable standard
        logger.info("Enable standards: %s", str(standard_to_be_enabled))
        client.batch_enable_standards(
            StandardsSubscriptionRequests=standard_to_be_enabled
        )
        ready = False
        while not ready:
            response = client.get_enabled_standards()
            subscription_statuses = [
                subscription["StandardsStatus"]
                for subscription in response["StandardsSubscriptions"]
            ]
            ready = all(
                (status in ("READY", "INCOMPLETE") for status in subscription_statuses)
            )
            if not ready:
                if "FAILED" in subscription_statuses:
                    logger.error(
                        "Standard could not be enabled: %s",
                        str(response["StandardsSubscriptions"]),
                    )
                    raise SecurityStandardUpdateError(
                        "Security standard could not be enabled: "
                        + str(response["StandardsSubscriptions"])
                    )
            logger.info("Wait until standards are enabled...")
            time.sleep(1)
        if "INCOMPLETE" in subscription_statuses:
            logger.info(
                "Standard could not be enabled completely. Some controls may not be available: %s",
                str(response["StandardsSubscriptions"]),
            )
        logger.info("Standards enabled")
        standards_changed = True

    if len(standard_to_be_disabled) > 0:
        # disable standard
        logger.info("Disable standards: %s", str(standard_to_be_disabled))
        client.batch_disable_standards(
            StandardsSubscriptionArns=standard_to_be_disabled
        )
        ready = False
        while not ready:
            response = client.get_enabled_standards()
            subscription_statuses = [
                subscription["StandardsStatus"]
                for subscription in response["StandardsSubscriptions"]
            ]
            ready = all(
                (status in ("READY", "INCOMPLETE") for status in subscription_statuses)
            )
            if not ready:
                if "FAILED" in subscription_statuses:
                    logger.error(
                        "Standard could not be disabled: %s",
                        str(response["StandardsSubscriptions"]),
                    )
                    raise SecurityStandardUpdateError(
                        "Security standard could not be disabled: "
                        + str(response["StandardsSubscriptions"])
                    )
            logger.info("Wait until standards are disabled...")
            time.sleep(1)
        if "INCOMPLETE" in subscription_statuses:
            logger.info(
                "Standard could not be enabled completely. Some controls may not be available: %s",
                str(response["StandardsSubscriptions"]),
            )
        logger.info("Standards disabled")
        standards_changed = True
    return standards_changed


def get_exceptions(event, region):
    """
    extract exceptions related to the processed account from event. Return dictionary.
    """
    exceptions_dict = event["exceptions"]
    account_id = event["account"]
    exceptions = dict()
    exceptions["Disabled"] = []
    exceptions["Enabled"] = []
    exceptions["DisabledReason"] = dict()

    # Identify exceptions for this account
    for control in exceptions_dict.keys():
        disabled = False
        enabled = False
        try:
            if account_id in exceptions_dict[control]["Disabled"]:
                disabled = True
        except KeyError:
            logger.info('%s: No "Disabled" exceptions.', control)

        try:
            if account_id in exceptions_dict[control]["Enabled"]:
                if "Region" in exceptions_dict[control].keys():
                    if region not in exceptions_dict[control]["Region"]:
                        disabled = True
                        logger.info('%s: is going to be disabled in %s', control, region)
                else:
                    enabled = True
        except KeyError:
            logger.info('%s: No "Enabled" exceptions.', control)

        try:
            exceptions["DisabledReason"][control] = exceptions_dict[control][
                "DisabledReason"
            ]
        except KeyError as error:
            logger.error('%s: No "DisabledReason".', control)
            raise error

        if enabled and disabled:
            # Conflict - you cannot enable and disable a control at the same time - fallback to default settin in administrator account
            logger.info(
                "%s: Conflict - exception states that this control should be enabled AND disabled. Fallback to SecurityHub Administrator configuration.",
                control,
            )
        elif disabled:
            exceptions["Disabled"].append(control)

        elif enabled:
            exceptions["Enabled"].append(control)
    return exceptions


def convert_regions(response, member_account_id):
    """
    Convert Items from DynamoDB into simpler dictionary format
    """
    account_regions = dict()
    for account in response['Items']:
        account_regions[account["AccountId"]["S"]] = [entry["S"] for entry in account["Regions"]["L"]]
    if member_account_id in account_regions.keys():
        return account_regions[member_account_id]
    else:
        logger.info("%s not in DDB items", member_account_id)


def lambda_handler(event, context):
    logger.info(event)

    global dynamodb_client
    if not dynamodb_client:
        dynamodb_client = boto3.client("dynamodb")
    response = dynamodb_client.scan(TableName=os.environ["RegionsDynamoDB"])

    try:
        # set variables and boto3 clients
        config = Config(
            retries={
                'max_attempts': 23,
                'mode': 'standard'
                }
            )
        administrator_account_id = context.invoked_function_arn.split(":")[4]
        member_account_id = event["account"]
        regions = convert_regions(response, member_account_id)

        role_arn = os.environ["MemberRole"].replace("<accountId>", member_account_id)
        global sts_client
        if not sts_client:
            sts_client = boto3.client("sts")
        assumed_role_object = sts_client.assume_role(
            RoleArn=role_arn, RoleSessionName="SecurityHubUpdater"
        )
        credentials = assumed_role_object["Credentials"]

        for region in regions:
            administrator_security_hub_client = boto3.client("securityhub", config=config,
                                                             region_name=region)
            # Get standard subscription controls
            standards = administrator_security_hub_client.describe_standards()
            # Get enabled standards
            administrator_enabled_standards = get_enabled_standard_subscriptions(
                standards, administrator_account_id, administrator_security_hub_client, region)

            member_security_hub_client = boto3.client(
                "securityhub",
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"],
                config=config, region_name=region
            )

            member_enabled_standards = get_enabled_standard_subscriptions(
                standards, member_account_id, member_security_hub_client, region
            )
            logger.info("Update Account %s in %s region", member_account_id, region)

            # Update standard subscriptions in member account
            standards_updated = update_standard_subscription(
                administrator_enabled_standards,
                member_enabled_standards,
                member_security_hub_client,
            )
            if standards_updated:
                logger.info("Fetch enabled standards again.")
                member_enabled_standards = get_enabled_standard_subscriptions(
                    standards, member_account_id, member_security_hub_client, region
                )
            # Get Controls
            standard_controls = get_controls(member_enabled_standards, member_security_hub_client)

            # Get exceptions
            exceptions = get_exceptions(event, region)
            logger.info("Exceptions: %s", str(exceptions))

            # Disable/enable the controls in member account

            update_member(standard_controls, member_security_hub_client, exceptions)

    except botocore.exceptions.ClientError as error:
        logger.error(error)
        return {"statusCode": 500, "account": member_account_id, "error": str(error)}

    return {"statusCode": 200, "account": member_account_id}
