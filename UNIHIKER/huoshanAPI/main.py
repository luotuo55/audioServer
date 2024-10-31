#coding=utf-8

import asyncio
import base64
import gzip
import hmac
import json
import logging
import os
import uuid
import wave
from enum import Enum
from hashlib import sha256
from io import BytesIO
from typing import List
from urllib.parse import urlparse
import time
import websockets
from unihiker import Audio, GUI

# 全局变量
gui = GUI()
audio = Audio()
is_recording = False
recording_start_time = 0
elapsed_time = 0
time_text = None
result_text = None
current_audio_file = None

# 配置参数
appid = "your_appid"
token = "your_token"
cluster = "your_cluster"

class AudioType(Enum):
    REALTIME = 2  # 实时录音

class AsrWsClient:
    def __init__(self, cluster, **kwargs):
        self.cluster = cluster
        self.success_code = 1000
        self.appid = kwargs.get("appid", "")
        self.token = kwargs.get("token", "")
        self.ws_url = kwargs.get("ws_url", "wss://openspeech.bytedance.com/api/v2/asr")
        self.uid = kwargs.get("uid", "streaming_asr_demo")
        self.workflow = kwargs.get("workflow", "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate")
        self.show_utterances = True
        self.result_type = "single"
        self.format = "wav"
        self.rate = 16000
        self.bits = 16
        self.channel = 1
        self.codec = "raw"

    def construct_request(self, reqid):
        req = {
            'app': {
                'appid': self.appid,
                'cluster': self.cluster,
                'token': self.token,
            },
            'user': {
                'uid': self.uid
            },
            'request': {
                'reqid': reqid,
                'workflow': self.workflow,
                'show_utterances': self.show_utterances,
                'result_type': self.result_type,
                "sequence": 1
            },
            'audio': {
                'format': self.format,
                'rate': self.rate,
                'bits': self.bits,
                'channel': self.channel,
                'codec': self.codec
            }
        }
        return req

    def token_auth(self):
        return {'Authorization': f'Bearer {self.token}'}

    async def process_realtime(self, ws):
        global current_audio_file, is_recording
        
        chunk_size = 3200  # 每次处理100ms的音频数据
        last_size = 0
        
        while is_recording and current_audio_file:
            try:
                if os.path.exists(current_audio_file):
                    current_size = os.path.getsize(current_audio_file)
                    if current_size > last_size:
                        with open(current_audio_file, 'rb') as f:
                            f.seek(last_size)
                            audio_data = f.read(chunk_size)
                            
                            if audio_data:
                                # 压缩音频数据
                                payload_bytes = gzip.compress(audio_data)
                                
                                # 构建音频请求
                                audio_request = bytearray(generate_audio_default_header())
                                audio_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
                                audio_request.extend(payload_bytes)
                                
                                # 发送音频数据
                                await ws.send(audio_request)
                                
                                # 接收识别结果
                                res = await ws.recv()
                                result = parse_response(res)
                                
                                if result and 'payload_msg' in result:
                                    payload_msg = result['payload_msg']
                                    if payload_msg.get('code') == 1000:
                                        results = payload_msg.get('result', [])
                                        if results and isinstance(results, list):
                                            for res in results:
                                                text = res.get('text', '')
                                                if text:
                                                    print_status(f"实时识别: {text}")
                                                    update_result_text(f"识别结果:\n{text}")
                                
                                last_size = current_size
                
                await asyncio.sleep(0.1)
                
            except Exception as e:
                print_status(f"处理音频流时发生错误: {e}")
                break

    async def execute(self):
        try:
            # 构建初始请求
            reqid = str(uuid.uuid4())
            request_params = self.construct_request(reqid)
            payload_bytes = str.encode(json.dumps(request_params))
            payload_bytes = gzip.compress(payload_bytes)
            
            full_client_request = bytearray(generate_full_default_header())
            full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
            full_client_request.extend(payload_bytes)

            header = self.token_auth()
            async with websockets.connect(self.ws_url, extra_headers=header) as ws:
                # 发送初始请求
                await ws.send(full_client_request)
                res = await ws.recv()
                result = parse_response(res)
                
                if 'payload_msg' in result and result['payload_msg']['code'] == self.success_code:
                    await self.process_realtime(ws)
                
        except Exception as e:
            print_status(f"语音识别过程发生错误: {e}")
            return None

def start_recording():
    global is_recording, recording_start_time, current_audio_file
    
    if not is_recording:
        print_status("开始录音")
        try:
            # 创建临时文件
            current_audio_file = os.path.join(tempfile.gettempdir(), f"recording_{int(time.time())}.wav")
            
            # 启动录音
            audio.start_record(current_audio_file)
            is_recording = True
            recording_start_time = time.time()
            update_gui()
            
            # 启动语音识别
            asr_client = AsrWsClient(
                cluster=cluster,
                appid=appid,
                token=token
            )
            asyncio.run(asr_client.execute())
            
        except Exception as e:
            print_status(f"开始录音时发生错误: {e}")
            is_recording = False

# ... (其他GUI相关函数保持不变) ...
