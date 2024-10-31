import json
import uuid
import gzip
import asyncio
import websockets
import numpy as np
import sounddevice as sd
import nest_asyncio
from unihiker import GUI
import time
from tkinter import END
import requests
import os
import dashscope

# 配置参数
appid = "4166554764"    # 项目的 appid
token = "ggmUTHHMXio-nJlKMkRvqEgkcWyfDK0K"    # 项目的 token
cluster = "volcengine_streaming_common"  # 请求的集群

# 协议常量
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
NO_SEQUENCE = 0b0000
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

# 添加一个全局标志来控制语音识别
is_recording = True

# 初始化GUI
gui = GUI()

# 创建标题
title = gui.draw_text(
    x=120,
    y=20,
    text="背诵助手",
    font_size=20,
    origin='center'
)

# 创建文本框
text_box = gui.add_text_box(
    x=120,
    y=140,
    w=220,
    h=180,
    origin='center',
    font_size=12
)

# 创建纠正文本按钮
correction_button = gui.add_button(
    x=120,
    y=270,
    w=160,
    h=36,
    text="纠正文本",
    origin='center'
)

def generate_header(
    version=PROTOCOL_VERSION,
    message_type=CLIENT_FULL_REQUEST,
    message_type_specific_flags=NO_SEQUENCE,
    serial_method=JSON,
    compression_type=GZIP,
    reserved_data=0x00,
    extension_header=bytes()
):
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

def parse_response(res):
    """解析响应"""
    try:
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
    except Exception as e:
        return {"error": f"Failed to parse response: {str(e)}"}

class AsrWsClient:
    def __init__(self, appid, token, cluster):
        self.appid = appid
        self.token = token
        self.cluster = cluster
        self.ws_url = "wss://openspeech.bytedance.com/api/v2/asr"
        self.success_code = 1000
        self.uid = "streaming_asr_demo"
        self.workflow = "audio_in,resample,partition,vad,fe,decode,itn,nlu_punctuate"
        self.show_language = False
        self.show_utterances = True
        self.result_type = "single"
        self.format = "raw"
        self.rate = 16000
        self.language = "zh-CN"
        self.bits = 16
        self.channel = 1
        self.codec = "raw"
        self.auth_method = "token"

    def construct_request(self, reqid):
        return {
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
                'nbest': 1,
                'workflow': self.workflow,
                'show_language': self.show_language,
                'show_utterances': self.show_utterances,
                'result_type': self.result_type,
                'sequence': 1
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

    def token_auth(self):
        return {'Authorization': f'Bearer; {self.token}'}

    async def process_microphone(self):
        """实时麦克风录音并识别"""
        global is_recording
        is_recording = True
        
        reqid = str(uuid.uuid4())
        request_params = self.construct_request(reqid)
        
        # 构造初始请求
        payload_bytes = str.encode(json.dumps(request_params))
        payload_bytes = gzip.compress(payload_bytes)
        full_request = bytearray(generate_full_default_header())
        full_request.extend(len(payload_bytes).to_bytes(4, 'big'))
        full_request.extend(payload_bytes)

        print("建立WebSocket连接...")
        async with websockets.connect(
            self.ws_url, 
            extra_headers=self.token_auth(), 
            max_size=1000000000
        ) as ws:
            # 发送初始请求
            await ws.send(full_request)
            response = await ws.recv()
            result = parse_response(response)
            print(f"初始化响应: {result}")
            
            if 'payload_msg' in result and result['payload_msg']['code'] == self.success_code:
                print("初始化成功")
                print("录音任务已启动")
                chunk_size = 9600
                
                with sd.InputStream(channels=1, samplerate=16000, dtype=np.int16, blocksize=chunk_size) as stream:
                    print("开始录音...")
                    try:
                        while is_recording:
                            audio_data, overflowed = stream.read(chunk_size)
                            if overflowed:
                                print("警告：音频缓冲区溢出")
                                
                            # 转换为字节
                            audio_bytes = audio_data.tobytes()
                            
                            # 压缩音频数据
                            compressed_audio = gzip.compress(audio_bytes)
                            
                            # 构造音频数据请求
                            audio_request = bytearray(generate_audio_default_header())
                            audio_request.extend(len(compressed_audio).to_bytes(4, 'big'))
                            audio_request.extend(compressed_audio)
                            
                            # 发送音频数据
                            await ws.send(audio_request)
                            
                            # 接收识别结果
                            response = await ws.recv()
                            result = parse_response(response)
                            
                            # 处理识别结果
                            if 'payload_msg' in result and 'result' in result['payload_msg']:
                                utterances = result['payload_msg']['result'][0].get('utterances', [])
                                for utterance in utterances:
                                    if not utterance['definite']:
                                        print(f"\r[识别中...] {utterance['text']}", end='', flush=True)
                                    else:
                                        print(f"\n[最终结果] {utterance['text']}")
                                        update_recognition_text(utterance['text'])
                    except KeyboardInterrupt:
                        print("\n录音已停止")
                    except Exception as e:
                        print(f"录音过程发生错误: {e}")
            else:
                print(f"初始化失败: {result['payload_msg'].get('message')}")

def update_recognition_text(new_text, is_correction=False):
    """更新识别结果并保持滚动条在底部"""
    try:
        prefix = "[纠正结果] " if is_correction else ""
        text_box.text.insert(END, prefix + new_text + "\n")
        text_box.text.see(END)
        gui.update()
    except Exception as e:
        print(f"更新文本错误: {e}")

def call_qwen_api(text):
    """调用通义千问API进行文本纠正"""
    try:
        print(f"开始调用API，输入文本：{text}")
        messages = [
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            {'role': 'user', 'content': f'下面的文字是语音识别后的结果，请剔除不必要的标点符号，替换错误的文字，最终返回正确的结果。语音识别文字如下：{text}'}
        ]
        
        response = dashscope.Generation.call(
            api_key=os.getenv('DASHSCOPE_API_KEY'),
            model="qwen-plus",
            messages=messages,
            result_format='message'
        )
        
        if response.status_code == 200:
            result = response.output.choices[0].message.content
            print(f"API调用成功，返回结果：{result}")
            return result
        else:
            error_msg = f"API调用失败: {response.message}"
            print(error_msg)
            return error_msg
    except Exception as e:
        error_msg = f"API调用错误: {str(e)}"
        print(error_msg)
        return error_msg

def on_correction_click():
    """处理纠正按钮点击事件"""
    global is_recording
    try:
        print("纠正按钮被点击")
        
        # 1. 停止语音识别
        is_recording = False
        print("正在停止语音识别...")
        time.sleep(1)  # 给一点时间让录音线程完全停止
        
        # 2. 获取当前文本
        current_text = text_box.text.get("1.0", END)
        print(f"获取到的当前文本：{current_text}")
        
        if current_text.strip():
            # 3. 调用API进行纠正
            print("开始调用API进行纠正...")
            corrected_text = call_qwen_api(current_text)
            print(f"API返回的纠正结果：{corrected_text}")
            
            # 4. 显示纠正结果
            update_recognition_text(corrected_text, is_correction=True)
            print("更新显示完成")
        else:
            print("文本框为空，不进行API调用")
            
    except Exception as e:
        error_msg = f"纠正文本错误: {str(e)}"
        print(error_msg)
        update_recognition_text(error_msg, is_correction=True)

# 绑定纠正按钮点击事件
correction_button.config(command=on_correction_click)

# 设置API密钥
os.environ['DASHSCOPE_API_KEY'] = 'sk-7c04ee6f9432492bb344baa7a5c0162f'

# 在notebook中运行异步代码的辅助函数
import nest_asyncio
nest_asyncio.apply()

# 创建客户端实例并运行
client = AsrWsClient(appid, token, cluster)
try:
    # 创建一个新的事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 启动语音识别任务
    recognition_task = loop.create_task(client.process_microphone())
    
    # 主循环
    while True:
        try:
            loop.run_until_complete(asyncio.sleep(0.1))
            gui.update()
            
        except KeyboardInterrupt:
            break
            
except Exception as e:
    print(f"\n程序异常: {e}")
finally:
    loop.close()
    print("程序已退出")