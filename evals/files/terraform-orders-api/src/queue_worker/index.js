// SQS(jobs)→ この Lambda → DynamoDB(orders)を更新
const { DynamoDBClient, UpdateItemCommand } = require("@aws-sdk/client-dynamodb");
const ddb = new DynamoDBClient({});
exports.handler = async (event) => {
  for (const record of event.Records) {
    await ddb.send(new UpdateItemCommand({ TableName: process.env.TABLE_NAME, Key: {} }));
  }
};
