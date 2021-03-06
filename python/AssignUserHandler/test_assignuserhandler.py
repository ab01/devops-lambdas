import unittest
import json
from assign_user_handler import AssignUserHandler
from moto import mock_dynamodb2, mock_sqs, mock_ec2, mock_cloudformation
import httpretty
import boto3

class TestAssignUserHandler(unittest.TestCase):
    def _get_good_message(self):
        return "{\"message\":{\"result\": [{\"updatedAt\": \"2015-08-10T06:53:11Z\", \"lastName\": \"Taylor\", \"firstName\": \"Dan\", \"createdAt\": \"2014-09-18T20:56:57Z\", \"email\": \"daniel.taylor@alfresco.com\", \"id\": 1558511}], \"success\": true, \"requestId\": \"e809#14f22884e5f\"}, \"stack_id\": \"some_random_stack_id\", \"stack_url\": \"https://www.testurl.com\"}"

    def _get_bad_message(self):
        message = json.loads("{\"message\":{\"result\": [{\"updatedAt\": \"2015-08-10T06:53:11Z\", \"lastName\": \"Taylor\", \"firstName\": \"Dan\", \"createdAt\": \"2014-09-18T20:56:57Z\", \"email\": \"daniel.taylor@alfresco.com\", \"id\": 1558511}], \"success\": true, \"requestId\": \"e809#14f22884e5f\"}, \"stack_id\": \"some_random_stack_id\", \"stack_url\": \"https://www.testurl.com\"}")
        message.pop('message')
        return message

    def _register_marketo_auth(self):
        httpretty.enable()
        httpretty.register_uri(
            method=httpretty.GET,
            uri="https://453-liz-762.mktorest.com/identity/oauth/token?client_secret=thesecret&grant_type=client_credentials&client_id=35a7e1a3-5e60-40b2-bd54-674680af2adc",
            status=200,
            body="{\"access_token\":\"random_access_token\"}"
        )

    def _get_handler_without_queue(self):
        return AssignUserHandler(
            'https://453-liz-762.mktorest.com',
            '35a7e1a3-5e60-40b2-bd54-674680af2adc',
            'thesecret'
        )

    def _get_handler_with_queue(self, url):
        return AssignUserHandler(
            'https://453-liz-762.mktorest.com',
            '35a7e1a3-5e60-40b2-bd54-674680af2adc',
            'thesecret',
            queue_url=url
        )

    @httpretty.activate
    def test_instance(self):
        """test_instance"""
        print "\ntest_instance(): "
        self._register_marketo_auth()
        handler_without_queue = self._get_handler_without_queue()
        self.assertIsNotNone(handler_without_queue.sqs_client)
        self.assertIsNotNone(handler_without_queue.dynamo_client)
        self.assertIsNone(handler_without_queue.queue_url) # will be none until we mock sqs
        self.assertIsNotNone(handler_without_queue.marketo_client)
        httpretty.disable()
        httpretty.reset()

    def test_is_valid_message(self):
        """test_is_valid_message"""
        print "\ntest_is_valid_message(): "
        handler_without_queue = self._get_handler_without_queue()
        message = json.loads(self._get_good_message())
        # With an expected message test message is valid
        self.assertTrue(handler_without_queue.is_valid_message(message))

        # Fumble around with the message to test is invalid
        message.pop('stack_id', None)
        self.assertFalse(handler_without_queue.is_valid_message(message))
        message.pop('stack_url', None)
        self.assertFalse(handler_without_queue.is_valid_message(message))
        message.pop('message', None)
        self.assertFalse(handler_without_queue.is_valid_message(message))

    def test_create_password(self):
        """test_create_password"""
        # proves that 10000 unique passwords are being created
        print "\ntest_create_password(): "
        handler_without_queue = self._get_handler_without_queue()
        passwords_list = []
        size = 10000
        for _ in range(0, size):
            passwords_list.append(handler_without_queue.create_password())

        passwords_set = set(passwords_list)
        self.assertEquals(len(passwords_set), size)

    @httpretty.activate
    @mock_sqs
    def test_get_message_from_queue(self):
        """test_get_message_from_queue"""
        # first create dummy queue and add message to it
        print "\ntest_get_message_from_queue(): "
        message = json.loads(self._get_good_message())
        sqs = boto3.resource('sqs')
        new_queue = sqs.create_queue(QueueName='test-queue')
        queue = sqs.get_queue_by_name(QueueName='test-queue')
        self._register_marketo_auth()
        handler = self._get_handler_with_queue(queue.url)

        # Call handler function to get message, should be none
        messages = handler.get_message_from_queue(queue.url)
        self.assertIsNone(messages)

        # Now test handler function to get the message
        msg = queue.send_message(MessageBody=json.dumps(message))
        messages = handler.get_message_from_queue(queue.url)
        self.assertTrue(len(messages) > 0)
        self.assertEquals(message, json.loads(messages[0]['Body']))
        httpretty.disable()
        httpretty.reset()

    @httpretty.activate
    def test_add_item_to_table(self):
        """test_add_item_to_table"""
        print "\ntest_add_item_to_table(): "
        with mock_dynamodb2():
            item = self._get_bad_message()
            self._register_marketo_auth()
            handler_without_queue = self._get_handler_without_queue()
            table = handler_without_queue.dynamo_client.create_table(
                TableName='assign_user_table',
                KeySchema=[
                    {
                        'AttributeName': 'LeadId',
                        'KeyType': 'HASH'  # Partition key
                    },
                    {
                        'AttributeName': 'Date',
                        'KeyType': 'RANGE'  # Sort key
                    }
                ],
                AttributeDefinitions=[
                    {
                        'AttributeName': 'LeadId',
                        'AttributeType': 'N'
                    },
                    {
                        'AttributeName': 'Date',
                        'AttributeType': 'S'
                    },
                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            )
            response = handler_without_queue.add_item_to_table(item, "assign_user_table")
            self.assertFalse(response)

            item = json.loads(self._get_good_message())
            response = handler_without_queue.add_item_to_table(item, "assign_user_table")
            self.assertTrue(response)

    @httpretty.activate
    def test_assign_user_to_stack(self):
        """test_assign_user_to_stack"""
        print "test_assign_user_to_stack"
        message = self._get_bad_message()
        self._register_marketo_auth()
        handler_without_queue = self._get_handler_without_queue()
        response = handler_without_queue.assign_user_to_stack(message)
        self.assertFalse(response)

        httpretty.register_uri(
            httpretty.POST,
            "{}/alfresco/service/api/people".format(message['stack_url']),
            body=""
        )
        message = json.loads(self._get_good_message())
        response = handler_without_queue.assign_user_to_stack(message)
        self.assertTrue(response)

        httpretty.register_uri(
            httpretty.POST,
            "{}/alfresco/service/api/people".format(message['stack_url']),
            body="",
            status=503
        )
        response = handler_without_queue.assign_user_to_stack(message)
        self.assertFalse(response)
        httpretty.disable()
        httpretty.reset()

    @httpretty.activate
    @mock_cloudformation
    @mock_ec2
    def test_update_marketo_lead(self):
        """test_update_marketo_lead"""
        # pass in a bad message first, should not be a success
        print "test_update_marketo_lead"
        message = self._get_bad_message()
        self._register_marketo_auth()

        httpretty.register_uri(
            httpretty.POST,
            "https://453-liz-762.mktorest.com/rest/v1/leads.json",
            body="{\"result\": [{\"updatedAt\": \"2015-08-10T06:53:11Z\", \"lastName\": \"Taylor\", \"firstName\": \"Dan\", \"createdAt\": \"2014-09-18T20:56:57Z\", \"email\": \"daniel.taylor@alfresco.com\", \"id\": 1558511}], \"success\": true, \"requestId\": \"e809#14f22884e5f\"}"
        )
        handler_without_queue = self._get_handler_without_queue()
        password = handler_without_queue.create_password()
        response = handler_without_queue.update_marketo_lead(message, password)
        self.assertFalse(response['success'])
        self.assertEquals(response['attempts'], 0)

        # pass in a good message
        message = json.loads(self._get_good_message())
        response = handler_without_queue.update_marketo_lead(message, password)
        self.assertTrue(response['success'])
        self.assertEquals(response['attempts'], 1)
        httpretty.disable()
        httpretty.reset()

    # @httpretty.activate
    # @mock_cloudformation
    # @mock_ec2
    # def test_failed_update_marketo_lead(self):
    #     """test_failed_update_marketo_lead"""
    #     # good message, bad response 404
    #     print "test_failed_update_marketo_lead"
    #     message = json.loads(self._get_good_message())
    #     self._register_marketo_auth()

    #     httpretty.register_uri(
    #         httpretty.POST,
    #         "https://453-liz-762.mktorest.com/rest/v1/leads.json",
    #         body="{\"result\": [{\"updatedAt\": \"2015-08-10T06:53:11Z\", \"lastName\": \"Taylor\", \"firstName\": \"Dan\", \"createdAt\": \"2014-09-18T20:56:57Z\", \"email\": \"daniel.taylor@alfresco.com\", \"id\": 1558511}], \"success\": false, \"requestId\": \"e809#14f22884e5f\", \"errors\":[{\"code\": 404, \"message\":\"The lead was not found\"}]}"
    #     )
    #     handler_without_queue = self._get_handler_without_queue()
    #     password = handler_without_queue.create_password()
    #     response = handler_without_queue.update_marketo_lead(message, password)
    #     self.assertEquals(response['attempts'], 5)
    #     self.assertFalse(response['success'])
    #     httpretty.disable()
    #     httpretty.reset()

if __name__ == '__main__':
    unittest.main()
