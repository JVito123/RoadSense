"""Send MQTT command to phone A or webcam B without dashboard UI."""
import argparse
import json
import ssl
import time
import uuid
import paho.mqtt.client as mqtt
p=argparse.ArgumentParser()
p.add_argument('--project-id',required=True)
p.add_argument('--target',choices=['A','B'],required=True)
p.add_argument('--value',type=float,required=True,help='B: motion score; A: vibration RMS')
p.add_argument('--jerk',type=float,default=3.0,help='A only: peak jerk threshold')
a=p.parse_args()
base=f'roadsense/{a.project_id}'
cmd={'command':'SET_THRESHOLD','target':a.target}
if a.target=='A':
    cmd.update(vibration_rms_threshold=a.value,jerk_peak_threshold=a.jerk)
else:
    cmd['motion_score_threshold']=a.value
c=mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,client_id='roadsense-command-'+uuid.uuid4().hex[:8])
c.tls_set_context(ssl.create_default_context())
def on_connect(client, userdata, flags, reason_code, properties):
    print('connect:',reason_code,flush=True)
    if reason_code == 0:
        client.subscribe(f'{base}/ack/{a.target}',qos=1)
        client.publish(f'{base}/control',json.dumps(cmd),qos=1)
        print('SENT',json.dumps(cmd),flush=True)
def on_message(client,userdata,msg):
    print('ACK:',msg.payload.decode(),flush=True)
c.on_connect=on_connect
c.on_message=on_message
c.connect('broker.hivemq.com',8883,keepalive=45)
c.loop_start()
time.sleep(4)
c.loop_stop()
c.disconnect()
