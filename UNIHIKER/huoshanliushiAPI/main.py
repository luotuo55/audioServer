"""
requires Python 3.6 or later

pip install asyncio
pip install websockets
"""

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
import pyaudio
import numpy as np
import queue
import threading

# 只保留必要的配置
appid = "4166554764"    # 项目的 appid
token = "ggmUTHHMXio-nJlKMkRvqEgkcWyfDK0K"    # 项目的 token
cluster = "volcengine_streaming_common"  # 请求的集群

PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001

PROTOCOL_VERSION_BITS = 4
HEADER_BITS = 4
MESSAGE_TYPE_BITS = 4
MESSAGE_TYPE_SPECIFIC_FLAGS_BITS = 4
MESSAGE_SERIALIZATION_BITS = 4
MESSAGE_COMPRESSION_BITS = 4
RESERVED_BITS = 8

# Message Type:
CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY_REQUEST = 0b0010
SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

# Message Type Specific Flags
NO_SEQUENCE = 0b0000  # no check sequence
POS_SEQUENCE = 0b0001
NEG_SEQUENCE = 0b0010
NEG_SEQUENCE_1 = 0b0011

# Message Serialization
NO_SERIALIZATION = 0b0000
JSON = 0b0001
THRIFT = 0b0011
CUSTOM_TYPE = 0b1111

# Message Compression
NO_COMPRESSION = 0b0000
GZIP = 0b0001
CUSTOM_COMPRESSION = 0b1111

AUDIO_CONFIG = {
    "chunk_size": 9600,
    "format": pyaudio.paInt16,
    "channels": 1,
    "rate": 16000,
    "max_silence": 300  # 最大静音时间(秒)
}

def generate_header(
    version=PROTOCOL_VERSION,
    message_type=CLIENT_FULL_REQUEST,
    message_type_specific_flags=NO_SEQUENCE,
    serial_method=JSON,
    compression_type=GZIP,
    reserved_data=0x00,
    extension_header=bytes()
):
    """
    protocol_version(4 bits), header_size(4 bits),
    message_type(4 bits), message_type_specific_flags(4 bits)
    serialization_method(4 bits) message_compression(4 bits)
    reserved （8bits) 保留字段
    header_extensions 扩展头(小等于 8 * 4 * (header_size - 1) )
    """
    header = bytearray()
    header_size = int(len(extension_header) / 4) + 1
    header.append((version << 4) | header_size)
    header.append((message_type << 4) | message_type_specific_flags)
    header.append((serial_method << 4) | compression_type)
    header.append(reserved_data)
    header.extend(extension_header)
    return header


def generate_full_default_header():
    return generate_header()


def generate_audio_default_header():
    return generate_header(
        message_type=CLIENT_AUDIO_ONLY_REQUEST
    )


def generate_last_audio_default_header():
    return generate_header(
        message_type=CLIENT_AUDIO_ONLY_REQUEST,
        message_type_specific_flags=NEG_SEQUENCE
    )

def parse_response(res):
    """
    protocol_version(4 bits), header_size(4 bits),
    message_type(4 bits), message_type_specific_flags(4 bits)
    serialization_method(4 bits) message_compression(4 bits)
    reserved （8bits) 保留字段
    header_extensions 扩展头(大小等于 8 * 4 * (header_size - 1) )
    payload 类似与http 请求体
    """
    protocol_version = res[0] >> 4
    header_size = res[0] & 0x0f
    message_type = res[1] >> 4
    message_type_specific_flags = res[1] & 0x0f
    serialization_method = res[2] >> 4
    message_compression = res[2] & 0x0f
    reserved = res[3]
    header_extensions = res[4:header_size * 4]
    payload = res[header_size * 4:]
    result = {}
    payload_msg = None
    payload_size = 0
    if message_type == SERVER_FULL_RESPONSE:
        payload_size = int.from_bytes(payload[:4], "big", signed=True)
        payload_msg = payload[4:]
    elif message_type == SERVER_ACK:
        seq = int.from_bytes(payload[:4], "big", signed=True)
        result['seq'] = seq
        if len(payload) >= 8:
            payload_size = int.from_bytes(payload[4:8], "big", signed=False)
            payload_msg = payload[8:]
    elif message_type == SERVER_ERROR_RESPONSE:
        code = int.from_bytes(payload[:4], "big", signed=False)
        result['code'] = code
        payload_size = int.from_bytes(payload[4:8], "big", signed=False)
        payload_msg = payload[8:]
    if payload_msg is None:
        return result
    if message_compression == GZIP:
        payload_msg = gzip.decompress(payload_msg)
    if serialization_method == JSON:
        payload_msg = json.loads(str(payload_msg, "utf-8"))
    elif serialization_method != NO_SERIALIZATION:
        payload_msg = str(payload_msg, "utf-8")
    result['payload_msg'] = payload_msg
    result['payload_size'] = payload_size
    return result


def read_wav_info(data: bytes = None) -> (int, int, int, int, int):
    with BytesIO(data) as _f:
        wave_fp = wave.open(_f, 'rb')
        nchannels, sampwidth, framerate, nframes = wave_fp.getparams()[:4]
        wave_bytes = wave_fp.readframes(nframes)
    return nchannels, sampwidth, framerate, nframes, len(wave_bytes)

class AudioType(Enum):
    LOCAL = 1  # 使用本地音频文件
    MICROPHONE = 2  # 使用麦克风录音

class AsrWsClient:
    def __init__(self, cluster, **kwargs):
        """
        :param cluster: 集群名称
        :param kwargs: 其他参数
        """
        self.cluster = cluster
        self.success_code = 1000  # success code, default is 1000
        self.seg_duration = int(kwargs.get("seg_duration", 15000))
        self.nbest = int(kwargs.get("nbest", 1))
        self.appid = kwargs.get("appid", "")
        self.token = kwargs.get("token", "")
        self.ws_url = kwargs.get("ws_url", "wss://openspeech.bytedance.com/api/v2/asr")
        self.uid = kwargs.get("uid", "streaming_asr_demo")
        self.workflow = kwargs.get("workflow", "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate")
        self.show_language = kwargs.get("show_language", False)
        self.show_utterances = kwargs.get("show_utterances", False)
        self.result_type = kwargs.get("result_type", "full")
        self.format = kwargs.get("format", "wav")
        self.rate = kwargs.get("sample_rate", 16000)
        self.language = kwargs.get("language", "zh-CN")
        self.bits = kwargs.get("bits", 16)
        self.channel = kwargs.get("channel", 1)
        self.codec = kwargs.get("codec", "raw")
        self.audio_type = kwargs.get("audio_type", AudioType.LOCAL)
        self.secret = kwargs.get("secret", "access_secret")
        self.auth_method = kwargs.get("auth_method", "token")
        self.mp3_seg_size = int(kwargs.get("mp3_seg_size", 10000))
        # audio_path 现在是可选的
        self.audio_path = kwargs.get("audio_path", None)

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
                'nbest': self.nbest,
                'workflow': self.workflow,
                'show_language': self.show_language,
                'show_utterances': self.show_utterances,
                'result_type': self.result_type,
                "sequence": 1
            },
            'audio': {
                'format': self.format,
                'rate': self.rate,
                'language': self.language,
                'bits': self.bits,
                'channel': self.channel,
                'codec': self.codec
            }
        }
        return req

    @staticmethod
    def slice_data(data: bytes, chunk_size: int) -> (list, bool):
        """
        slice data
        :param data: wav data
        :param chunk_size: the segment size in one request
        :return: segment data, last flag
        """
        data_len = len(data)
        offset = 0
        while offset + chunk_size < data_len:
            yield data[offset: offset + chunk_size], False
            offset += chunk_size
        else:
            yield data[offset: data_len], True

    def _real_processor(self, request_params: dict) -> dict:
        pass

    def token_auth(self):
        return {'Authorization': 'Bearer; {}'.format(self.token)}

    def signature_auth(self, data):
        header_dicts = {
            'Custom': 'auth_custom',
        }

        url_parse = urlparse(self.ws_url)
        input_str = 'GET {} HTTP/1.1\n'.format(url_parse.path)
        auth_headers = 'Custom'
        for header in auth_headers.split(','):
            input_str += '{}\n'.format(header_dicts[header])
        input_data = bytearray(input_str, 'utf-8')
        input_data += data
        mac = base64.urlsafe_b64encode(
            hmac.new(self.secret.encode('utf-8'), input_data, digestmod=sha256).digest())
        header_dicts['Authorization'] = 'HMAC256; access_token="{}"; mac="{}"; h="{}"'.format(self.token,
                                                                                              str(mac, 'utf-8'), auth_headers)
        return header_dicts

    async def segment_data_processor(self, wav_data: bytes, segment_size: int):
        reqid = str(uuid.uuid4())
        request_params = self.construct_request(reqid)
        payload_bytes = str.encode(json.dumps(request_params))
        payload_bytes = gzip.compress(payload_bytes)
        full_client_request = bytearray(generate_full_default_header())
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)
        header = None
        if self.auth_method == "token":
            header = self.token_auth()
        elif self.auth_method == "signature":
            header = self.signature_auth(full_client_request)
        async with websockets.connect(self.ws_url, extra_headers=header, max_size=1000000000) as ws:
            await ws.send(full_client_request)
            res = await ws.recv()
            result = parse_response(res)
            if 'payload_msg' in result and result['payload_msg']['code'] != self.success_code:
                yield result
                return
            for seq, (chunk, last) in enumerate(AsrWsClient.slice_data(wav_data, segment_size), 1):
                payload_bytes = gzip.compress(chunk)
                audio_only_request = bytearray(generate_audio_default_header())
                if last:
                    audio_only_request = bytearray(generate_last_audio_default_header())
                audio_only_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
                audio_only_request.extend(payload_bytes)
                await ws.send(audio_only_request)
                res = await ws.recv()
                result = parse_response(res)
                
                if 'payload_msg' in result and 'result' in result['payload_msg']:
                    if self.show_utterances and self.result_type == "single":
                        for utterance in result['payload_msg']['result'][0].get('utterances', []):
                            yield {
                                'text': utterance['text'],
                                'is_final': utterance['definite'],
                                'start_time': utterance['start_time'],
                                'end_time': utterance['end_time']
                            }
                    else:
                        yield result
                
                if 'payload_msg' in result and result['payload_msg']['code'] != self.success_code:
                    return

    async def execute(self):
        with open(self.audio_path, mode="rb") as _f:
            data = _f.read()
        audio_data = bytes(data)
        if self.format == "mp3":
            segment_size = self.mp3_seg_size
        elif self.format == "wav":
            nchannels, sampwidth, framerate, nframes, wav_len = read_wav_info(audio_data)
            size_per_sec = nchannels * sampwidth * framerate
            segment_size = int(size_per_sec * self.seg_duration / 1000)
        else:
            raise Exception("format should be wav or mp3")
        
        async for result in self.segment_data_processor(audio_data, segment_size):
            yield result


async def execute_one(audio_item, cluster, **kwargs):
    assert 'id' in audio_item
    assert 'path' in audio_item
    audio_id = audio_item['id']
    audio_path = audio_item['path']
    audio_type = AudioType.LOCAL
    asr_http_client = AsrWsClient(
        audio_path=audio_path,
        cluster=cluster,
        audio_type=audio_type,
        **kwargs
    )
    results = []
    async for result in asr_http_client.execute():
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))  # 实时打印每个结果
    return {"id": audio_id, "path": audio_path, "results": results}

async def test_full_result():
    print("Testing full result:")
    result = await execute_one(
        {
            'id': 1,
            'path': audio_path
        },
        cluster=cluster,
        appid=appid,
        token=token,
        format=audio_format,
        show_utterances=False,
        result_type="full"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

async def test_single_utterance():
    print("\nTesting single utterance result:")
    result = await execute_one(
        {
            'id': 2,
            'path': audio_path
        },
        cluster=cluster,
        appid=appid,
        token=token,
        format=audio_format,
        show_utterances=True,
        result_type="single"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

async def record(audio_queue):
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    SAMPLE_RATE = 16000
    CHUNK = int(SAMPLE_RATE / 10)  # 每次读取100ms的数据

    audio = pyaudio.PyAudio()
    stream = audio.open(format=FORMAT,
                       channels=CHANNELS,
                       rate=SAMPLE_RATE,
                       input=True,
                       frames_per_buffer=CHUNK)
    
    print("开始录音...")
    bytes_acc = bytes()
    try:
        while True:
            audio_chunk = stream.read(CHUNK, exception_on_overflow=False)
            bytes_acc += audio_chunk
            
            if len(bytes_acc) >= CHUNK * 5:  # 累积500ms的数据
                print("发送音频数据...")  # 调试信息
                await audio_queue.put(bytes_acc)
                bytes_acc = bytes()
            await asyncio.sleep(0.01)
    except Exception as e:
        print(f"录音错误: {e}")
    finally:
        print("关闭录音流...")
        stream.stop_stream()
        stream.close()
        audio.terminate()

async def process_microphone():
    ws = None
    audio_stream = None
    try:
        audio_queue = asyncio.Queue()
        
        asr_client = AsrWsClient(
            cluster=cluster,
            appid=appid,
            token=token,
            format="wav",
            audio_type=AudioType.MICROPHONE,
            sample_rate=16000,
            channel=1,
            bits=16
        )

        # 首先建立WebSocket连接
        reqid = str(uuid.uuid4())
        request_params = asr_client.construct_request(reqid)
        payload_bytes = str.encode(json.dumps(request_params))
        payload_bytes = gzip.compress(payload_bytes)
        full_client_request = bytearray(generate_full_default_header())
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)

        header = asr_client.token_auth()
        
        async with websockets.connect(asr_client.ws_url, extra_headers=header) as ws:
            print("WebSocket连接已建立")
            await ws.send(full_client_request)
            res = await ws.recv()
            result = parse_response(res)
            print("初始化响应:", json.dumps(result, ensure_ascii=False))

            # 动录音任务
            record_task = asyncio.create_task(record(audio_queue))
            print("录音任务已启动")

            try:
                while True:
                    audio_data = await audio_queue.get()
                    print(f"处理音频数据，长度: {len(audio_data)}")
                    
                    # 发送音频数据
                    payload_bytes = gzip.compress(audio_data)
                    audio_only_request = bytearray(generate_audio_default_header())
                    audio_only_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
                    audio_only_request.extend(payload_bytes)
                    
                    await ws.send(audio_only_request)
                    res = await ws.recv()
                    result = parse_response(res)
                    if 'payload_msg' in result:
                        print("识别结果:", json.dumps(result['payload_msg'], ensure_ascii=False))
                    
            except KeyboardInterrupt:
                print("收到停止信号...")
            except Exception as e:
                print(f"处理错误: {e}")
                raise
            finally:
                print("正在清理...")
                record_task.cancel()
                try:
                    await record_task
                except asyncio.CancelledError:
                    pass

    except KeyboardInterrupt:
        print("接收到退出信号")
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        # 清理资源
        print("正在清理资源...")
        if audio_stream:
            try:
                audio_stream.stop_stream()
                audio_stream.close()
                print("音频流已关闭")
            except Exception as e:
                print(f"关闭音频流时出错: {e}")
        
        if ws:
            try:
                await ws.close()
                print("WebSocket连接已关闭")
            except Exception as e:
                print(f"关闭WebSocket时出错: {e}")

def cleanup():
    try:
        if websocket:
            websocket.close()
        if audio_stream:
            audio_stream.stop_stream()
            audio_stream.close()
        if p:
            p.terminate()
    except Exception as e:
        print(f"清理资源时发生错误: {e}")
    finally:
        print("清理完成")

class AudioStreamHandler:
    def __init__(self):
        self.is_running = False
        self.total_processed = 0
        
    def start_streaming(self):
        self.is_running = True
        while self.is_running:
            # 处理音频流
            self.total_processed += 1
            
    def stop_streaming(self):
        self.is_running = False

if __name__ == '__main__':
    try:
        asyncio.run(process_microphone())
    except KeyboardInterrupt:
        print("程序被用户中断")
    except Exception as e:
        print(f"程序异常退出: {e}")
    finally:
        print("程序已退出")
