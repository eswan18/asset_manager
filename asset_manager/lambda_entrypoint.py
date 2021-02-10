from .dashboard import make_charts

def lambda_handler(event, context):
    return {
      'statusCode': 200,
      'body': 'HELLO'
    }
