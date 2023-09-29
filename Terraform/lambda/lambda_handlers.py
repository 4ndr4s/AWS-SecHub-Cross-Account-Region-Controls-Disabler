import boto3
import logging
import json
import os


logger = logging.getLogger()
logger.setLevel(logging.INFO)
items_table = os.environ["ItemsDynamoDB"]
regions_table = os.environ["RegionsDynamoDB"]


def put_item(control_data, table_name):
    #API expect data in dictionary format
    database = boto3.resource('dynamodb')
    table = database.Table(table_name)
    table.put_item(Item=control_data)


def update_item(control_data, table_name):
    database = boto3.resource('dynamodb')
    table = database.Table(table_name)
    if "Enabled" in control_data:
        table.update_item(
            Key={
                'ControlId': control_data['ControlId']
            },
            UpdateExpression='REMOVE Disabled SET Enabled = :val1',
            ExpressionAttributeValues={
                ':val1': control_data["Enabled"]
            }
        )
    elif "Disabled" in control_data:
        table.update_item(
            Key={
                'ControlId': control_data['ControlId']
            },
            UpdateExpression='REMOVE Enabled SET Disabled = :val1, DisabledReason = :val2',
            ExpressionAttributeValues={
                ':val1': control_data["Disabled"],
                ':val2': control_data["DisabledReason"]
            }
        )
    else:
        logger.info("%s at least one attribute is required", control_data)


def process_item(items, controls, table_name, item_type):
    controls_in_ddb = []
    for item in items['Items']:
        logger.info("%s items", items['Items'])
        controls_in_ddb.append(item[item_type]["S"])
    for control in controls:
        if control[item_type] in controls_in_ddb:
            logger.info("%s item in DDB table updating", control[item_type])
            update_item(control, table_name)
        else:
            logger.info("%s item not in DDB table adding", control[item_type])
            put_item(control, table_name)


def get_s3_data(bucket, json_file):
    s3_client = boto3.client('s3')
    items_data = json.loads(s3_client.get_object(
        Bucket=bucket, Key=str(os.environ["json_file"]))['Body'].read())
    logger.info(" items_data: %s", items_data)
    return items_data


def lambda_handler(event, context):
    logger.info("%s event", event)
    bucket = event['Records'][0]['s3']['bucket']['name']
    ## processing items.json
    items_data = get_s3_data(bucket, os.environ["items_json_file"])
    logger.info(" items_data: %s", items_data)
    dynamodb_client = boto3.client("dynamodb")
    logger.info("items table name: %s", items_table)
    response = dynamodb_client.scan(TableName=items_table)
    process_item(response, items_data, items_table, item_type="ControlId")

    ## processing accounts.json
    accounts_data = get_s3_data(bucket, os.environ["accounts_json_file"])
    logger.info(" items_data: %s", items_data)
    dynamodb_client = boto3.client("dynamodb")
    logger.info("accounts-region table name: %s", regions_table)
    response = dynamodb_client.scan(TableName=regions_table)
    process_item(response, accounts_data, regions_table, item_type="AccountId")