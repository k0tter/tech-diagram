// SQS → transform: DynamoDB(events) を更新
const { DynamoDBClient, UpdateItemCommand } = require("@aws-sdk/client-dynamodb");
const ddb = new DynamoDBClient({});
exports.handler = async (event) => {
  for (const r of event.Records) {
    await ddb.send(new UpdateItemCommand({ TableName: process.env.TABLE_NAME, Key: {} }));
  }
};
