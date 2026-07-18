// API Gateway → この Lambda → DynamoDB(orders)/ SQS(jobs) へジョブ投入
const { DynamoDBClient, PutItemCommand } = require("@aws-sdk/client-dynamodb");
const { SQSClient, SendMessageCommand } = require("@aws-sdk/client-sqs");
const ddb = new DynamoDBClient({});
const sqs = new SQSClient({});
exports.handler = async (event) => {
  await ddb.send(new PutItemCommand({ TableName: process.env.TABLE_NAME, Item: {} }));
  await sqs.send(new SendMessageCommand({ QueueUrl: process.env.QUEUE_URL, MessageBody: "job" }));
  return { statusCode: 200 };
};
