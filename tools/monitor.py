"""Monitor MQTT telemetry/events/ACK without the UI; useful for integration."""
import argparse
import json
import ssl
import uuid
import paho.mqtt.client as mqtt

p = argparse.ArgumentParser()
p.add_argument('--project-id', required=True)
a = p.parse_args()
base=f'roadsense/{a.project_id}'
c=mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,client_id='roadsense-monitor-'+uuid.uuid4().hex[:8])
c.tls_set_context(ssl.create_default_context())
def on_connect(client, userdata, flags, reason_code, properties):
    print('Connected:', reason_code, flush=True)
    if reason_code == 0:
        client.subscribe([(f'{base}/edge/+/telemetry',0),(f'{base}/events',1),(f'{base}/ack/+',1)])
def on_message(client,userdata,msg):
    try:
        data=json.loads(msg.payload.decode())
        print(msg.topic, json.dumps(data,ensure_ascii=False),flush=True)
    except Exception as e:
        print(msg.topic, 'unreadable:', e,flush=True)
c.on_connect=on_connect
c.on_message=on_message
c.connect('broker.hivemq.com',8883,keepalive=45)
print('Watching',base,'(Ctrl+C to quit)')
c.loop_forever()
