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




# 初始化GUI
gui = GUI()

# 创建标题
title = gui.draw_text(
    x=120,
    y=30,
    text="语音识别系统",
    font_size=24,
    origin='center'
)

# 创建文本框
text_box = gui.add_text_box(
    x=120,      # 中心x坐标
    y=160,      # 中心y坐标
    w=220,      # 宽度
    h=200,      # 高度
    origin='center',  # 居中对齐
    font_size=14
)

# 存储所有识别文本
all_texts = []

def update_recognition_text(new_text):
    """更新识别结果并保持滚动条在底部"""
    try:
        # 添加新文本到列表
        all_texts.append(new_text)
        
        # 更新文本框内容
        full_text = "\n".join(all_texts)
        text_box.config(text=full_text)
        
        # 滚动到底部
        text_box.text.see(END)
        
        # 更新GUI
        if gui.master.winfo_exists():
            gui.update()
            
    except Exception as e:
        print(f"更新文本错误: {e}")

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
                chunk_size = 9600  # 每次读取的采样点数
                
                with sd.InputStream(
                    channels=1, 
                    samplerate=16000,
                    dtype=np.int16,
                    blocksize=chunk_size,
                    callback=None
                ) as stream:
                    print("开始录音...")
                    try:
                        while True:
                            # 读取音
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
                        # 发送最后一个音频包
                        last_request = bytearray(generate_last_audio_default_header())
                        last_request.extend(len(compressed_audio).to_bytes(4, 'big'))
                        last_request.extend(compressed_audio)
                        await ws.send(last_request)
                        print("\n录音已停止")
                    except Exception as e:
                        print(f"录音过程发生错误: {e}")
            else:
                print(f"初始化失败: {result['payload_msg'].get('message')}")

# 在notebook中运行异步代码的辅助函数
import nest_asyncio
nest_asyncio.apply()

# 创建客户端实例并运行
client = AsrWsClient(appid, token, cluster)
try:
    loop = asyncio.get_event_loop()
    loop.run_until_complete(client.process_microphone())
except KeyboardInterrupt:
    print("\n程序已被用户中断")
except Exception as e:
    print(f"\n程序异常: {e}")
finally:
    print("程序已退出")

def update_text_with_scroll(new_text):
    """更新文本并滚动到底部"""
    try:
        # 获取当前内容并追加新文本
        current_text = text_box.text.get("1.0", "end-1c")  # end-1c 去掉最后的换行符
        updated_text = current_text + new_text + "\n"
        
        # 更新文本内容
        text_box.text.delete("1.0", "end")
        text_box.text.insert("1.0", updated_text)
        
        # 强制滚动到底部
        text_box.text.yview_moveto(1.0)
        
        # 更新GUI
        if hasattr(gui, 'update'):
            gui.update()
            
    except Exception as e:
        print(f"更新文本错误: {e}")

# 测试文本更新
count = 1
while True:
    try:
        # 添加新文本
        new_text = f"这是第 {count} 行测试文本"
        update_text_with_scroll(new_text)
        
        count += 1
        time.sleep(1)
        
    except KeyboardInterrupt:
        break

def update_recognition_text(new_text):
    """更新识别结果并滚动到底部"""
    current_text = text_box.text.get("1.0", "end")  # 获取当前内容
    text_box.config(text=current_text + new_text + "\n")  # 追加新内容并换行
    text_box.text.see("end")  # 滚动到底部

# 在识别结果处理部分使用：
if result_data['result'][0].get('is_final'):
    text = result_data['result'][0].get('text', '')
    print(f"识别结果: {text}")
    update_recognition_text(text)

