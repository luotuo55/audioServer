import os
import time
import json
import requests
from unihiker import Audio
import dashscope
from dashscope.audio.asr import Transcription
import threading

# 服务器API地址
SERVER_URL = "http://www.52ai.fun"
API_URL = f"{SERVER_URL}/api/upload"

# API密钥
SERVER_API_KEY = "1F1vmARoSjXRTDvywh9XtbnR8vd74AfffF0t0jn3qhM"
dashscope.api_key = 'sk-7c04ee6f9432492bb344baa7a5c0162f'

# 音频采集设置
SAMPLE_RATE = 16000
CHANNELS = 1  # 单声道
MAX_DURATION = 60  # 最大录音时长(秒)

def record_audio():
    print("开始录音...")
    print("再次按 Enter 键结束录音...")
    audio = Audio()
    audio_file = "/tmp/recording.wav"
    
    stop_recording = threading.Event()
    
    def wait_for_stop():
        input()  # 等待用户按 Enter 键
        stop_recording.set()
    
    threading.Thread(target=wait_for_stop, daemon=True).start()
    
    try:
        audio.record(audio_file, MAX_DURATION)
        start_time = time.time()
        while not stop_recording.is_set() and time.time() - start_time < MAX_DURATION:
            time.sleep(0.1)
        audio.stop()
        print("录音完成")
        time.sleep(1)  # 额外等待1秒确保文件保存
        print(f"录音已保存为 {audio_file}")
        return audio_file
    except Exception as e:
        print(f"录音过程中发生错误: {e}")
        return None

def upload_audio(file_path):
    if not os.path.exists(file_path):
        print(f"错误：文件 {file_path} 不存在")
        return None

    try:
        with open(file_path, 'rb') as audio_file:
            headers = {
                'Content-Type': 'audio/wav',
                'X-API-Key': SERVER_API_KEY
            }
            print(f"正在上传文件到 {API_URL}")
            response = requests.post(API_URL, data=audio_file, headers=headers)
        
        if response.status_code == 200:
            print("文件上传成功")
            result = response.json()
            print("服务器响应:", result)
            if 'file_url' in result:
                audio_url = result['file_url']
                print(f"服务器返回的音频URL: {audio_url}")
                return audio_url
            else:
                print("警告：服务器响应中没有 file_url 字段")
        elif response.status_code == 401:
            print("上传失败：无效的 API 密钥")
        else:
            print(f"上传失败，状态码: {response.status_code}")
            print("服务器响应:", response.text)
        return None
    except requests.RequestException as e:
        print(f"上传过程中发生错误: {e}")
        return None

def submit_transcription_task(file_url):
    task_response = Transcription.async_call(
        model='paraformer-v2',
        file_urls=[file_url],
        language_hints=['zh', 'en']
    )
    return task_response.output.task_id

def fetch_transcription_result(task_id):
    return Transcription.fetch(task=task_id)

def poll_transcription_task(task_id, max_attempts=30, interval=2):
    for attempt in range(max_attempts):
        response = fetch_transcription_result(task_id)
        status = response.output.task_status
        print(f"尝试 {attempt + 1}: 任务状态 - {status}")
        if status in ['SUCCEEDED', 'FAILED']:
            return response
        time.sleep(interval)
    print("任务轮询超时")
    return None

def display_transcription_result(detailed_result):
    print("\n详细转录结果:")
    print(f"文件 URL: {detailed_result['file_url']}")
    print(f"音频格式: {detailed_result['properties']['audio_format']}")
    print(f"采样率: {detailed_result['properties']['original_sampling_rate']} Hz")
    print(f"时长: {detailed_result['properties']['original_duration_in_milliseconds']} ms")
    
    for transcript in detailed_result['transcripts']:
        print(f"\n通道 ID: {transcript['channel_id']}")
        print(f"内容时长: {transcript['content_duration_in_milliseconds']} ms")
        print(f"完整文本: {transcript['text']}")
        
        print("\n句子:")
        for sentence in transcript['sentences']:
            print(f"  {sentence['begin_time']} - {sentence['end_time']} ms: {sentence['text']}")
            
            print("  词:")
            for word in sentence['words']:
                print(f"    {word['begin_time']} - {word['end_time']} ms: {word['text']}{word['punctuation']}")

def main():
    while True:
        input("按 Enter 键开始录音...")
        
        audio_file = record_audio()
        if audio_file:
            audio_url = upload_audio(audio_file)
            if audio_url:
                print("正在进行语音识别...")
                task_id = submit_transcription_task(audio_url)
                print(f"任务已提交。任务 ID: {task_id}")

                final_response = poll_transcription_task(task_id)

                if final_response and final_response.output.task_status == 'SUCCEEDED':
                    print("转录成功完成。")
                    
                    for result in final_response.output.results:
                        print(f"\n处理文件: {result['file_url']}")
                        detailed_result = get_detailed_transcription(result['transcription_url'])
                        if detailed_result:
                            display_transcription_result(detailed_result)
                        else:
                            print("获取详细转录结果失败。")
                else:
                    print("转录失败或超时。")
            else:
                print("音频文件上传失败")
        else:
            print("录音失败")
        
        time.sleep(2)  # 等待2秒后准备下一次录音

if __name__ == "__main__":
    main()
