from flask import Flask, request, send_file, jsonify
from difflib import SequenceMatcher
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
import threading
import socket
import psutil
import sys

# Flask 应用
app = Flask(__name__)

# 共享数据存储
class SharedData:
    def __init__(self):
        self.speech_recognition_results = []
        self.latest_text = ""
        self.target_text = ""
        self.latest_score = None

shared_data = SharedData()

# Web 服务器路由
@app.route('/')
def index():
    return send_file('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    try:
        print("收到提交请求")  # 调试信息
        data = request.get_json()
        print(f"接收到的数据: {data}")  # 调试信息
        
        if not data:
            print("未接收到数据")
            return jsonify({"status": "error", "message": "未接收到数据"}), 400
            
        text = data.get('text', '').strip()
        print(f"提取的文本: {text}")  # 调试信息
        
        if not text:
            print("文本为空")
            return jsonify({"status": "error", "message": "范文不能为空"}), 400
            
        shared_data.target_text = text
        print(f"已保存范文: {shared_data.target_text}")  # 调试信息
        
        return jsonify({
            "status": "success", 
            "message": "范文提交成功",
            "text_length": len(text)
        })
        
    except Exception as e:
        print(f"提交处理错误: {str(e)}")  # 调试信息
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_score')
def get_score():
    if shared_data.latest_score:
        score_data = shared_data.latest_score
        # 返回后清除分数，避免重复获取
        shared_data.latest_score = None
        return jsonify({"status": "success", "data": score_data})
    return jsonify({"status": "waiting"})

# 相似度计算函数
def calculate_similarity(text1, text2):
    return SequenceMatcher(None, text1, text2).ratio()

def calculate_completeness(target_text, speech_text):
    target_words = set(target_text.split())
    speech_words = set(speech_text.split())
    common_words = target_words.intersection(speech_words)
    return len(common_words) / len(target_words) if target_words else 0

def get_similarity_comment(similarity):
    if similarity >= 0.9: return "非常接近"
    elif similarity >= 0.7: return "比较接近"
    elif similarity >= 0.5: return "部分接近"
    else: return "差异较大"

def get_completeness_comment(completeness):
    if completeness >= 0.9: return "内容完整"
    elif completeness >= 0.7: return "大部分完整"
    elif completeness >= 0.5: return "部分完整"
    else: return "内容缺失"

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

# 初始化 nest_asyncio
nest_asyncio.apply()

# 全局变量
is_recording = True
all_texts = []
gui = None
loop = None  # 添加全局 loop 变量

# 在程序最开始处（所有 import 语句之后）设置 API key
def init_api_keys():
    """初始化API密钥"""
    try:
        # 语音识别配置
        global appid, token, cluster
        appid = "4166554764"
        token = "ggmUTHHMXio-nJlKMkRvqEgkcWyfDK0K"
        cluster = "volcengine_streaming_common"
        
        # 千问API配置
        dashscope_key = 'sk-7c04ee6f9432492bb344baa7a5c0162f'
        os.environ['DASHSCOPE_API_KEY'] = dashscope_key
        dashscope.api_key = dashscope_key
        
        # 验证千问API key是否设置成功
        print(f"当前 DashScope API Key: {dashscope.api_key}")
        return True
        
    except Exception as e:
        print(f"API密钥初始化失败: {e}")
        return False

def call_qwen_api(text):
    """调用千问API进行文本纠错"""
    try:
        if not dashscope.api_key:
            print("[错误] DashScope API Key未设置")
            return None
            
        print(f"使用的API Key: {dashscope.api_key}")
        
        messages = [
            {
                'role': 'system',
                'content': '你是一个专业的文本纠错助手。请对输入的文本进行标点符号和错别字的修正，保持原文的意思不变。'
            },
            {
                'role': 'user',
                'content': f'请修正以下文本的标点符号和错别字：\n{text}'
            }
        ]
        
        response = dashscope.Generation.call(
            model='qwen-plus',
            messages=messages,
            result_format='message',
            api_key=dashscope.api_key  # 显式传递API key
        )
        
        if response.status_code == 200:
            corrected_text = response.output.choices[0].message.content.strip()
            print(f"[纠正结果] {corrected_text}")
            return corrected_text
        else:
            error_msg = f"API调用失败: {response.code} - {response.message}"
            print(f"[错误] {error_msg}")
            return None
            
    except Exception as e:
        error_msg = f"纠错API调用失败: {str(e)}"
        print(f"[错误] {error_msg}")
        return None

def on_correction_click():
    """处理纠正按钮点击事件"""
    global is_recording
    try:
        print("纠正按钮被点击")
        
        # 1. 停止语音识别
        is_recording = False
        print("正在停止语音识别...")
        time.sleep(1)
        
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

def on_score_click():
    """处理打分按钮点击事件"""
    global is_recording
    try:
        print("打分按钮被点击")
        
        # 1. 停止语音识别
        is_recording = False
        print("正在停止语音识别...")
        time.sleep(1)
        
        # 2. 获取当前文本
        current_text = text_box.text.get("1.0", END)
        print(f"获取到的朗读文本：{current_text}")
        
        # 3. 获取范文
        target_text = shared_data.target_text
        if not target_text:
            error_msg = "[错误] 请先在网页端输入范文"
            print(error_msg)
            update_recognition_text(error_msg)
            return
            
        if not current_text.strip():
            error_msg = "[错误] 请先进行语音识别"
            print(error_msg)
            update_recognition_text(error_msg)
            return
        
        print("开始调用API进行评分...")
        # 4. 构造提示词
        prompt = f"""
请对比以下两段文本，从准确度、完整度、流畅度三维度进行评分（满100分），并给出详细分析：

范文：
{target_text}

朗读文本：
{current_text}

请按以下格式输出：
准确度：XX分
完整度：XX分
流畅度：XX分
总分：XX分

详细分析：
1. 准确度分析：...
2. 完整度分析：...
3. 流畅度分析：...
4. 改进建议：...
"""
        
        # 5. 调用API进行评分
        response = dashscope.Generation.call(
            api_key=os.getenv('DASHSCOPE_API_KEY'),
            model="qwen-plus",
            messages=[
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': prompt}
            ],
            result_format='message'
        )
        
        if response.status_code == 200:
            result = response.output.choices[0].message.content
            print(f"评分结果：{result}")
            
            # 更新UNIHIKER显示
            update_recognition_text(f"[评分结果]\n{result}")
            
            # 更新共享数据供网页显示
            shared_data.latest_score = {
                "target_text": target_text,
                "speech_text": current_text,
                "score_result": result
            }
            
        else:
            error_msg = f"评分失败: {response.message}"
            print(error_msg)
            update_recognition_text(f"[错误] {error_msg}")
            
    except Exception as e:
        error_msg = f"评分错误: {str(e)}"
        print(error_msg)
        update_recognition_text(error_msg)

def init_gui():
    """初始化GUI，只调用一次"""
    global gui, text_box
    
    if gui is not None:
        print("GUI 已经初始化，跳过重复初始化")
        return gui, text_box
        
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
    
    # 创建纠正按钮 - 左边
    correction_button = gui.add_button(
        x=70,  # 移到左边
        y=290,  # 两个按钮在同一水平线上
        w=100,  # 减小按钮宽度
        h=36,
        text="纠正文本",
        origin='center',
        onclick=on_correction_click
    )
    
    # 创建打分按钮 - 右边
    score_button = gui.add_button(
        x=180,  # 移到右边
        y=290,  # 与纠正按钮在同一水平线上
        w=100,  # 减小按钮宽度
        h=36,
        text="文本打分",
        origin='center',
        onclick=on_score_click
    )
    
    return gui, text_box

def kill_existing_flask():
    """杀死已存在的Flask进程"""
    try:
        current_pid = os.getpid()
        
        for proc in psutil.process_iter(['pid', 'name', 'connections']):
            try:
                # 跳过当前进程
                if proc.pid == current_pid:
                    continue
                    
                for conn in proc.connections():
                    if conn.laddr.port == 5000:
                        print(f"发现端口5000被进程占用 (PID: {proc.pid})")
                        proc.kill()
                        print(f"已终止进程 {proc.pid}")
                        time.sleep(1)  # 等待进程完全终止
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        print(f"清理进程时出错: {e}")

def run_flask():
    """运行Flask服务器"""
    try:
        # 先尝试释放端口
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', 5000))
            sock.close()
        except Exception as e:
            print(f"端口绑定测试失败: {e}")
            # 尝试结束占用端口的进程
            try:
                import os
                os.system("fuser -k 5000/tcp")
                print("已尝试释放端口5000")
                time.sleep(2)
            except:
                print("无法释放端口，请手动结束占用端口的进程")
                return False

        ip = get_ip_address()
        server_info = """
╔════════════════════════════════════════════════╗
║             Web服务器启动信息                  ║
╠════════════════════════════════════════════════╣
║                                                ║
║  状态: 正在启动...                            ║
║  访问地址: http://{ip}:5000                   ║
║  本地地址: http://localhost:5000              ║
║  监听端口: 5000                               ║
║                                                ║
║  请在浏览器中访问以上地址来输入范文          ║
║                                                ║
╚════════════════════════════════════════════════╝
""".format(ip=ip)
        
        print("\n" + server_info, flush=True)
        
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        return True
    except Exception as e:
        print("\n" + "="*50)
        print("【服务器启动失败】")
        print(f"错误信息: {str(e)}")
        print("="*50 + "\n")
        return False

def get_ip_address():
    """获取本机IP地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

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
                    while is_recording:
                        audio_data, overflowed = stream.read(chunk_size)
                        if overflowed:
                            print("警告：音频缓冲区溢出")
                            
                        audio_bytes = audio_data.tobytes()
                        compressed_audio = gzip.compress(audio_bytes)
                        
                        audio_request = bytearray(generate_audio_default_header())
                        audio_request.extend(len(compressed_audio).to_bytes(4, 'big'))
                        audio_request.extend(compressed_audio)
                        
                        await ws.send(audio_request)
                        response = await ws.recv()
                        result = parse_response(response)
                        
                        if 'payload_msg' in result and 'result' in result['payload_msg']:
                            utterances = result['payload_msg']['result'][0].get('utterances', [])
                            for utterance in utterances:
                                if not utterance['definite']:
                                    print(f"\r[识别中...] {utterance['text']}", end='', flush=True)
                                else:
                                    print(f"\n[最终结果] {utterance['text']}")
                                    update_recognition_text(utterance['text'])

# 添加其他必要的函数
def generate_full_default_header():
    return generate_header()

def generate_header(
    version=PROTOCOL_VERSION,
    message_type=CLIENT_FULL_REQUEST,
    message_type_specific_flags=NO_SEQUENCE,
    serial_method=JSON,
    compression_type=GZIP,
    reserved_data=0x00,
    extension_header=bytes()
):
    """生成请求头"""
    header = bytearray()
    header_size = int(len(extension_header) / 4) + 1
    header.append((version << 4) | header_size)
    header.append((message_type << 4) | message_type_specific_flags)
    header.append((serial_method << 4) | compression_type)
    header.append(reserved_data)
    header.extend(extension_header)
    return header

def generate_audio_default_header():
    """生成音频数据请求头"""
    return generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST)

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

def update_recognition_text(new_text, is_correction=False):
    """更新识别结果并保持滚动条在底部"""
    try:
        prefix = "[纠正结果] " if is_correction else ""
        all_texts.append(prefix + new_text)
        
        full_text = "\n".join(all_texts)
        text_box.config(text=full_text)
        text_box.text.see(END)
        
        if gui.master.winfo_exists():
            gui.update()
            
    except Exception as e:
        print(f"更新文本错误: {e}")

@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "接口不存在"}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({"status": "error", "message": "服务器内部错误"}), 500

def cleanup():
    """程序退出时的清理工作"""
    global is_recording, loop
    try:
        is_recording = False
        if loop and not loop.is_closed():
            loop.close()
    except Exception as e:
        print(f"清理时出错: {e}")

if __name__ == '__main__':
    try:
        print("\n=== 程序启动顺序 ===")
        print("0. 初始化API密钥")
        print("1. 启动Web服务器")
        print("2. 初始化GUI界面")
        print("3. 启动语音识别\n")
        
        # 首先初始化API密钥
        if not init_api_keys():
            print("API密钥初始化失败，程序退出")
            sys.exit(1)
            
        # 1. 先启动Web服务器
        print("正在启动Web服务器...\n")
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        
        # 等待确保服务器启动
        time.sleep(5)  # 增加等待时间
        
        # 检查服务器是否成功启动
        try:
            response = requests.get('http://localhost:5000', timeout=3)
            if response.status_code != 200:
                raise Exception("服务器响应异常")
        except Exception as e:
            print(f"服务器启动检查失败: {e}")
            print("请确保端口5000未被占用")
            sys.exit(1)
        
        # 2. 初始化GUI
        print("\n正在初始化GUI...\n")
        gui, text_box = init_gui()
        
        # 3. 创建客户端实例并启动语音识别
        print("\n正在启动语音识别...\n")
        client = AsrWsClient(appid, token, cluster)
        
        # 4. 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        recognition_task = loop.create_task(client.process_microphone())
        
        # 5. 主循环
        while True:
            try:
                loop.run_until_complete(asyncio.sleep(0.1))
                gui.update()
                
            except KeyboardInterrupt:
                print("\n程序被用户中断")
                break
            except Exception as e:
                print(f"\n循环中出现错误: {e}")
                break
                
    except Exception as e:
        print(f"\n程序异常: {e}")
    finally:
        try:
            if 'loop' in locals() and loop and not loop.is_closed():
                loop.close()
        except Exception as e:
            print(f"关闭事件循环时出错: {e}")
        print("程序已正常退出")

# 设置API密钥
os.environ['DASHSCOPE_API_KEY'] = 'sk-7c04ee6f9432492bb344baa7a5c0162f'