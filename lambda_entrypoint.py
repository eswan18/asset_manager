from asset_manager.dashboard import make_charts

def lambda_handler(event, context):
    html = make_charts().to_html()
    return {
      'statusCode': 200,
      'body': html
    }
