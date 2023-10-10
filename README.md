# AWS-SecHub-Cross-Account-Region-Controls-Disabler

- [Introduction](#introduction)
- [Goal](#goal)
- [Overview](#overview)
- [Setup](#setup)
  - [Requirements](#requirements)
  - [Member Accounts](#member-accounts)
  - [Security Hub administrator account](#security-hub-administrator-account)
- [Usage](#usage)
  - [Setting exceptions](#setting-exceptions)
  - [Security Hub Controls CLI](#security-hub-controls-cli)
- [Workflow and Troubleshooting](#workflow-and-troubleshooting)
- [Customization](#customization)

## Introduction

This repo is based on [aws-security-hub-cross-account-controls-disabler](https://github.com/aws-samples/aws-security-hub-cross-account-controls-disabler) solution with some adittional features as described [here](https://dev.to/4ndr4s/disable-security-hub-controls-in-an-aws-organization-59jf-temp-slug-4251521?preview=a342149ee58b96950b3dc9533164cb181d7925d62cd276ee5cb3fd9b41c39b1d3a63b4ff7bd0803504c6c59c4f2d78acfdedd72c953ed4e742dbe19e):
-  Disable global resources control in specific regions.
- Iterate over multiple regions.
- Disable/Enable controls across security standards [consolidated controls view and consolidated control findings in AWS Security Hub](https://aws.amazon.com/blogs/security/prepare-for-consolidated-controls-view-and-consolidated-control-findings-in-aws-security-hub/)
- Enable/Disable Controls for the entire Organization without listing account IDs
- Event Trigger: The state machine is triggered each time an item is added/updated on dynamoDB table in the Security Hub administrator account.
- Control regions to run per account ID.
## Goal

In this blog, we will explore the process of enabling and disabling controls in [AWS Security Hub](https://docs.aws.amazon.com/securityhub/latest/userguide/what-is-securityhub.html) across multiple accounts within an organization, with a dedicated Security Hub administrator account. Although AWS Security Hub offers control management, there is no native method to globally disable specific controls for all Security Hub member accounts. To address this gap, this project aims to streamline the process by propagating the action of enabling or disabling security standards and their controls from the Security Hub administrator account to all member accounts. 

The solution presented in this blog builds upon an existing [AWS blog](https://aws.amazon.com/blogs/security/disabling-security-hub-controls-in-a-multi-account-environment/) post, enhancing it with the following key features:

- Common ControlID: We introduce the concept of enabling or disabling controls using a common ControlID across enabled standards, effectively resolving the [issue](https://github.com/aws-samples/aws-security-hub-cross-account-controls-disabler/issues/10) of control management.

- Global Controls: We address the challenge of enabling or disabling controls based on [regions](https://github.com/aws-samples/aws-security-hub-cross-account-controls-disabler/issues/11).

- Simplified Account Management: Instead of manually listing all account IDs, we provide a mechanism to enable or disable controls across the organization effortlessly.

- Security Hub Admin Account: We recognize the Security Hub Admin account as a member account.

- Integration with S3 and Lambda function: We implement S3 integration to initiate a State Machine execution whenever a new item is added to the DynamoDB table.

- AccountIds DynamoDB table: For large organizations with different business units is common to use different regions across the account within the organization, for this case we implement a DynamoDB to control regions per account.

## Overview

The proposed solution encompasses the following components:

**Cross-Account IAM Role**: Member accounts are equipped with a cross-account IAM role, granting the necessary Security Hub permissions to enable/disable Security standard controls.

**AWS Step Function State Machine**: This state machine assumes the cross-account IAM role and manages the enablement or disablement of controls in member accounts, ensuring alignment with the DynamoDB exceptions, ensuring the organization's compliance with the enabled standards in the Security Hub admin account.

**DynamoDB Table for Exceptions**: A DynamoDB table contains information about which controls should be enabled or disabled in specific accounts.

**DynamoDB Table for Accounts-Region**: A DynamoDB table contains information about which regions are enable per account.

**S3 Bucket**: An S3 bucket to upload of an [items.json](Terraform/lambda/items.json) file containing exceptions to be added to the DynamoDB table.

**Lambda Function**: This function is triggered when the [items.json](Terraform/lambda/items.json) file is updated in the S3 bucket, ensuring real-time updates to control exceptions in the DynamoDB table and initiating Step Function Machine executions in response to DynamoDB updates.

![Architecture](img/SecurityHubUpdater.png)



## Setup

### Requirements
To deploy this solution, you need:

- [AWS CLI V2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- [Terraform](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)

Also, make sure that one of the AWS accounts is designated as the [Security Hub administrator account](https://docs.aws.amazon.com/securityhub/latest/userguide/securityhub-accounts.html).

### Member Accounts
Deploy the cross-account IAM role defined in [member-iam-role/template.yaml](member-iam-role/template.yaml) in all member accounts.
For *SecurityHubAdminAccountId*, set the Account ID of the Security Hub administrator account.

#### Deployment
Replace *my-stackset* and *AccountID* with the desired value and create the stack-set.

```
aws cloudformation create-stack-set \
--stack-set-name <my-stackset> \
--template-body file://member-iam-role/template.yaml \
--capabilities CAPABILITY_NAMED_IAM \
--call-as DELEGATED_ADMIN --permission-model SERVICE_MANAGED\ --auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \
--parameters ParameterKey=SecurityHubAdminAccountId,ParameterValue=<AccountID>
```

#### Parameters
| Name                      | Description                                                                                       | Default                        |
|---------------------------|---------------------------------------------------------------------------------------------------|--------------------------------|
| SecurityHubAdminAccountId | Account ID of SecurityHub administrator Account                   | *None*                           |
| IAMRolePath               | Path for IAM Role - this must match the `MemberIAMRolePath` parameter in the `UpdateMembers` stack. | /                      |
| IAMRoleName               | Name of IAM Role - this must match the `MemberIAMRoleName` parameter in the `UpdateMembers` stack.    | securityhub-UpdateControl-role |

Create the stack instances, replace the *ORG-ID* with the desired OU-ID, if you want to deploy at organization level use your root OU-ID.

```
aws cloudformation create-stack-instances --stack-set-name my-stackset \
--deployment-targets OrganizationalUnitIds='["ORG-ID"]' \
--regions '["us-east-1"]'  --call-as DELEGATED_ADMIN \
--operation-preferences FailureTolerancePercentage=100,MaxConcurrentCount=20
```

### Security Hub administrator account

#### SAM

Deploy the state machine described in [CFN/template.yaml](CFN/template.yaml).

#### Prerequisites
Before proceeding with the [CFN/template.yaml](CFN/template.yaml) file, which utilizes the [Serverless transformation](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/transform-aws-serverless.html), it is essential to set up an artifact bucket within the Security Hub administrator account. To create this artifact bucket, you can use the following command, specifying your chosen name for the bucket as *<artifact-bucket>*:

```
aws s3 mb s3://<artifact-bucket>
```

#### Deployment
The artifact bucket created in the preqrequisites is referenced by `<artifact-bucket>` in the code below. Chose an arbitrary `<stack-name>` and execute following commands to deploy the [CFN/template.yaml](CFN/template.yaml):
```
sam package --template-file CFN/template.yaml --output-template-file CFN/template-out.yaml --s3-bucket <artifact-bucket>
aws cloudformation deploy --template-file CFN/template-out.yaml --capabilities CAPABILITY_IAM --stack-name <stack-name> --parameter-overrides SecurityHubAdminAccountId=<AccountID>
```

#### Parameters
| Name                      | Description                                                                                                  | Default                        |
|---------------------------|--------------------------------------------------------------------------------------------------------------|--------------------------------|
| Schedule |  The scheduling expression that determines when and how often the Security Hub Disabler runs.                             | rate(1 day)                           |
| MemberIAMRolePath         | Path of IAM Role in member account - this must match the `IAMRolePath` parameter in the `memeber-iam-role` stack. | /                      |
| MemberIAMRoleName         | Name of IAM Role in member account - this must match the `IAMRoleName` parameter in the `memeber-iam-role` stack.   | securityhub-UpdateControl-role |
| Path                      | Path of IAM LambdaExecution Roles                                                                            | /                      |
| EventTriggerState                      | The state of the SecurityHubUpdateEvent rule monitoring Security Hub control updates and triggering the state machine                                                                            | DISABLED                      |
| SecurityHubAdminAccountId | Account ID of SecurityHub administrator Account                   | *None*  
| NotificationEmail1                      | Optional - E-mail address to receive notification if the state machine fails.  |                       |
| NotificationEmail2                      | Optional - E-mail address to receive notification if the state machine fails.  |                       |
| NotificationEmail3                      | Optional - E-mail address to receive notification if the state machine fails.  |                       |

#### Terraform

To deploy this solution, navigate to the terraform folder, where you will find the necessary configurations to set up the solution. This includes the creation of an S3 bucket and a Lambda function, which plays a pivotal role in updating the DynamoDB table each time a new JSON file containing control status information is uploaded to the S3 bucket.


```
## terraform initialization
terraform init

## Execute the plan to evaluate changes
terraform plan

## execute apply
terraform apply
```

## Usage
Once the deployment is complete, the solution operates automatically, driven by the following triggers:
##### Scheduled Trigger

The Scheduled Trigger operates based on a predefined schedule, which can be customized using the Schedule parameter. By default, it runs daily. You have the flexibility to employ scheduling expressions as detailed in the AWS documentation [here](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-create-rule-schedule.html).
The Scheduled Trigger serves a dual purpose: it ensures that newly added accounts are promptly updated as Security Hub member accounts and propagates the status of controls that were previously disabled even before the solution deployment to all existing member accounts.

##### Event Trigger

The Event Trigger activates each time a control is disabled or enabled in the Security Hub administrator account. The behavior of the Event Trigger can be controlled via the EventTriggerState parameter, which can be set during the deployment process.
Limitation: If a lot of controls are changed in a very short timeframe (e.g. when done programmatically via Security Hub Controls CLI), the Event Trigger causes multiple parallel executions which may lead to API throttling and thus failure of the execution.

For specific cases where reflecting the control status of the admin account in member accounts is unnecessary, we have chosen to disable this trigger.

##### DynamoDB update events

The state machine is triggered after a file is updated or a new item or added in the S3 Bucket.

### Setting exceptions
Exceptions are managed through the DynamoDB table deployed in the SecurityHub administrator account. Each individual element within this table represents an exception. Every exception should include at least one AWS account associated with it.

Here's how the process works:

**Adding or Updating Exceptions**: Whenever a new exception is added or an existing one is updated, a Lambda function is invoked. This Lambda function, in turn, initiates the execution of a new State Machine.


To add exceptions edit the json file [items.json](Terraform/lambda/items.json), for guidance and reference, you may consult the [items.json.template](Terraform/lambda/items.json.template) file.


The following json object is an extraction of the [items.json](Terraform/lambda/items.json), for guidance and reference, you may consult the [items.json.template](Terraform/lambda/items.json.template) file:

```
  {
    "ControlId": "CloudTrail.5",
    "Disabled": [ "ALL" ],
    "DisabledReason": "We are not monitoring CT at Organization level, Jira Ticket XXX-01"
  },
  {
    "ControlId": "CloudTrail.6",
    "Disabled": ["123456789012", "123456789089", "123456789076"],
    "DisabledReason": "We are not monitoring CT at Organization level, Jira Ticket XXX-02"
  },
  {
      "ControlId": "IAM.9",
      "Enabled": ["ALL"],
      "DisabledReason": "Global resource control, should be enabled only in us-east-1, Jira Ticket XXX-03",
      "Region": ["us-east-1"]
  }


```

**Adding Organization-Wide Exceptions**: When adding an exception that applies to the entire organization, you can streamline the process by simply using the keyword "ALL". This eliminates the need to list individual accounts, making exception management more efficient and less error-prone.

**Disabling Global Controls**: To disable a global control, the key step is to use the "Enabled" parameter while specifying the region within which this control should be enabled. For example:


```
## Disable IAM.9 in all regions but us-east-1
  {
      "ControlId": "IAM.9",
      "Enabled": ["ALL"],
      "DisabledReason": "Global resource control, should be enabled only in us-east-1, Jira Ticket XXX-03",
      "Region": ["us-east-1"]
  }
```

**Implementing exceptions**: Once you've made updates to an element within the [items.json](Terraform/lambda/items.json) file and wish to apply these alterations, follow these steps:

- Save your modifications within the [items.json](Terraform/lambda/items.json) file.
- execute below terraform commands:


```
## Execute the plan to evaluate changes
terraform plan

## execute apply
terraform apply
```
**Adding or Updating Accounts**: Whenever a new account is added or an existing one is updated, a Lambda function is invoked. This Lambda function, in turn, initiates the execution of a new State Machine, to update or add accounts and regions update [accounts.json](Terraform/lambda/accounts.json) file as described below.

```
[
    {
      "AccountId": "123456789012",
      "Regions": [
        "ap-northeast-1",
        "ap-northeast-2",
        "ap-northeast-3",
        "ap-south-1",
        "ap-southeast-1",
        "ap-southeast-2",
        "ca-central-1",
        "eu-central-1",
        "eu-north-1",
        "eu-west-1",
        "eu-west-2",
        "eu-west-3",
        "sa-east-1",
        "us-east-2",
        "us-west-1",
        "us-west-2",
        "us-east-1"
      ]
    },
    {
      "AccountId": "123456789012",
      "Regions": [
        "us-east-2",
        "us-west-1",
        "us-west-2",
        "us-east-1"
      ]
    }
  ]
```

After saving your changes run terraform plan and apply again.

## Conclusion

In this blog, you learned how to disable some controls across multiple accounts within organization. we showed how the controls can quickly be disabled or enabled using the solution described. This project provide a solution to disable controls across different standards using a common controlID besides giving the option to disable controls for global resources. 

We also introduced a DynamoDb table to control regions per account, this additional feature is useful for large organizations with multiple business unit that requires different enabled regions per account.

If you have feedback about this post, submit comments in the Comments section below. If you have trouble with the solution, please open an issue in GitHub.

## Workflow and Troubleshooting

Since the solution is implemented via AWS Step Functions state machine, each execution can be inspected in the AWS Step Functions state machine dashboard.
