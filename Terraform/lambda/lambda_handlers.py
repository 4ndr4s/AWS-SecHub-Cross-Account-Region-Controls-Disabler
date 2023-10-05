import boto3
import logging
import json
import os


logger = logging.getLogger()
logger.setLevel(logging.INFO)


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


def item_update(account_data, table_name):
    database = boto3.resource('dynamodb')
    table = database.Table(table_name)
    table.update_item(
            Key={
                'AccountId': account_data['AccountId']
            },
            UpdateExpression='SET Regions = :val1',
            ExpressionAttributeValues={
                ':val1': account_data["Regions"]
            }
        )


def process_item(items, data, table_name, item_type):
    items_in_ddb = []
    for item in items['Items']:
        logger.info("%s items", items['Items'])
        items_in_ddb.append(item[item_type]["S"])
    for control in data:
        if control[item_type] in items_in_ddb:
            logger.info("%s item in DDB table updating", control[item_type])
            if item_type == "ControlId":
                update_item(control, table_name)
            else:
                item_update(control, table_name)
        else:
            logger.info("%s item not in DDB table adding", control[item_type])
            put_item(control, table_name)


def get_s3_data(bucket, json_file):
    s3_client = boto3.client('s3')
    items_data = json.loads(s3_client.get_object(
        Bucket=bucket, Key=str(os.environ["json_file"]))['Body'].read())
    logger.info(" items_data: %s", items_data)
    return items_data


def start_execution(table_name, state_machine_arn):
    # Initialize the DDB client
    db_client = boto3.client('dynamodb')
    db_status = db_client.describe_table(TableName=table_name)['Table']['TableStatus']
    while db_status != 'ACTIVE':
        db_status = db_client.describe_table(TableName=table_name)['Table']['TableStatus']
    else:
        client = boto3.client('stepfunctions')
        # Start the execution of the state machine
        execution_response = client.list_executions(
            stateMachineArn=state_machine_arn,
            statusFilter='RUNNING'
        )['executions']
        if execution_response:
            logger.info("%s State Machine execution in progress, skipping new execution", state_machine_arn)
        else:
            response = client.start_execution(
                stateMachineArn=state_machine_arn,
                input='{}'  # Replace with the input data for your state machine (JSON format)
            )
            execution_arn = response['executionArn']
            logger.info("execution started ID: %s", execution_arn)
            return {
                'statusCode': 200,
                'body': f'Started execution: {execution_arn}'
            }


def lambda_handler(event, context):
    logger.info("%s event", event)
    bucket = event['Records'][0]['s3']['bucket']['name']
    items_table = os.environ["ItemsDynamoDB"]
    regions_table = os.environ["RegionsDynamoDB"]
    state_machine_arn = os.environ["StateMachineArn"]
    dynamodb_client = boto3.client("dynamodb")
    ## processing accounts.json
    accounts_data = get_s3_data(bucket, os.environ["accounts_json_file"])
    logger.info(" accounts_data: %s", accounts_data)
    logger.info("accounts-region table name: %s", regions_table)
    regions_response = dynamodb_client.scan(TableName=regions_table)
    process_item(regions_response, accounts_data, regions_table, item_type="AccountId")
    
    ## processing items.json
    items_data = get_s3_data(bucket, os.environ["items_json_file"])
    logger.info(" items_data: %s", items_data)
    logger.info("items table name: %s", items_table)
    items_response = dynamodb_client.scan(TableName=items_table)
    process_item(items_response, items_data, items_table, item_type="ControlId")
    start_execution(items_table, state_machine_arn)
