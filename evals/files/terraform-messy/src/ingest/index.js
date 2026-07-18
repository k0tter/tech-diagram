// API Gateway → ingest: DynamoDB(events) へ記録し SQS へ投入
const { DynamoDBClient, PutItemCommand } = require("@aws-sdk/client-dynamodb");
const { SQSClient, SendMessageCommand } = require("@aws-sdk/client-sqs");
const ddb = new DynamoDBClient({}); const sqs = new SQSClient({});
exports.handler = async () => {
  await ddb.send(new PutItemCommand({ TableName: process.env.TABLE_NAME, Item: {} }));
  await sqs.send(new SendMessageCommand({ QueueUrl: process.env.QUEUE_URL, MessageBody: "x" }));
};
