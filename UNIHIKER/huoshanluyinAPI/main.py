#coding=utf-8  调用火山平台的录音识别API
import requests
import json
import time
import os
import uuid

s = requests

appid = '4166554764'
token = 'ggmUTHHMXio-nJlKMkRvqEgkcWyfDK0K'
cluster = 'volc_auc_meeting'
audio_url = 'http://www.52ai.fun/voice/67471138-d944-46be-b39f-bb9ebdc39879.wav'
service_url = 'https://openspeech.bytedance.com/api/v1/auc'

headers = {'Authorization': 'Bearer; {}'.format(token)}

def submit_task():
    request = {
        "app": {
            "appid": appid,
            "token": token,
            "cluster": cluster
        },
        "user": {
            "uid": "AUC7429515390483222847"
        },
        "audio": {
            "format": "wav",
            "url": audio_url
        },
        "additions": {
            'with_speaker_info': 'False',
        }
    }

    r = s.post(service_url + '/submit', data=json.dumps(request), headers=headers)
    resp_dic = json.loads(r.text)
    print(resp_dic)
    id = resp_dic['resp']['id']
    print(id)
    return id


def query_task(task_id):
    query_dic = {}
    query_dic['appid'] = appid
    query_dic['token'] = token
    query_dic['id'] = task_id
    query_dic['cluster'] = cluster
    query_req = json.dumps(query_dic)
    print(query_req)
    r = s.post(service_url + '/query', data=query_req, headers=headers)
    print(r.text)
    resp_dic = json.loads(r.text)
    return resp_dic


def file_recognize():
    task_id = submit_task()
    start_time = time.time()
    while True:
        time.sleep(2)
        # query result
        resp_dic = query_task(task_id)
        if resp_dic['resp']['code'] == 1000: # task finished
            print("success")
            exit(0)
        elif resp_dic['resp']['code'] < 2000: # task failed
            print("failed")
            exit(0)
        now_time = time.time()
        if now_time - start_time > 300: # wait time exceeds 300s
            print('wait time exceeds 300s')
            exit(0)


if __name__ == '__main__':
    file_recognize()