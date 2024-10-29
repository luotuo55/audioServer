import os
import time
import json
import requests
from unihiker import GUI, Audio
import dashscope
from dashscope.audio.asr import Transcription
import threading

# 初始化 Audio 和 GUI
audio = Audio()
gui = GUI()

# 服务器API地址
SERVER_URL = "http://www.52ai.fun"
API_URL = f"{SERVER_URL}/api/upload"

# API密钥
SERVER_API_KEY = "1F1vmARoSjXRTDvywh9XtbnR8vd74AfffF0t0jn3qhM"
dashscope.api_key = 'sk-7c04ee6f9432492bb344baa7a5c0162f'

# 全局变量
is_recording = False
audio_file = "/tmp/recording.wav"
recording_start_time = 0
elapsed_time = 0
time_text = None

def print_status(message):
    print(f"[状态] {message}")

def update_gui():
    global gui, time_text
    gui.clear()  # 清除之前的所有元素
    time_text = gui.draw_text(x=120, y=40, text="", origin='center')
    if is_recording:
        gui.add_button(x=120, y=100, w=160, h=60, text="录音中", origin='center', onclick=start_recording, name="start_button", state="disabled")
        gui.add_button(x=120, y=180, w=160, h=60, text="结束录音", origin='center', onclick=stop_recording, name="stop_button")
    else:
        gui.add_button(x=120, y=100, w=160, h=60, text="开始录音", origin='center', onclick=start_recording, name="start_button")
        gui.add_button(x=120, y=180, w=160, h=60, text="结束录音", origin='center', onclick=stop_recording, name="stop_button", state="disabled")
    gui.add_button(x=120, y=260, w=160, h=60, text="退出", origin='center', onclick=lambda: exit(), name="exit_button")

def update_time_text():
    global time_text
    if time_text:
        time_text.text = f"录音时间: {elapsed_time}秒"

def start_recording():
    global is_recording, recording_start_time, elapsed_time
    if not is_recording:
        print_status("开始录音按钮被点击")
        try:
            audio.start_record(audio_file)
            is_recording = True
            recording_start_time = time.time()
            elapsed_time = 0
            print_status("录音开始")
            update_gui()
        except Exception as e:
            print_status(f"开始录音时发生错误: {e}")

def stop_recording():
    global is_recording, elapsed_time
    if is_recording:
        print_status("结束录音按钮被点击")
        try:
            audio.stop_record()
            is_recording = False
            print_status("录音停止，开始处理音频")
            update_gui()
            threading.Thread(target=process_audio, daemon=True).start()
        except Exception as e:
            print_status(f"停止录音时发生错误: {e}")

def process_audio():
    global elapsed_time, gui
    print_status(f"录音完成，文件保存为: {audio_file}")
    gui.add_button(x=120, y=180, w=160, h=60, text="录音识别中...", origin='center', onclick=lambda: None, name="stop_button")
    
    audio_url = upload_audio(audio_file)
    if audio_url:
        print_status("音频文件上传成功，开始语音识别...")
        task_id = submit_transcription_task(audio_url)
        print_status(f"任务已提交。任务 ID: {task_id}")

        final_response = poll_transcription_task(task_id)

        if final_response and final_response.output.task_status == 'SUCCEEDED':
            print_status("转录成功完成。")
            
            for result in final_response.output.results:
                print_status(f"处理文件: {result['file_url']}")
                detailed_result = get_detailed_transcription(result['transcription_url'])
                if detailed_result:
                    display_transcription_result(detailed_result)
                else:
                    print_status("获取详细转录结果失败。")
        else:
            print_status("转录失败或超时。")
    else:
        print_status("音频文件上传失败")
    
    elapsed_time = 0
    update_gui()
    print_status("音频处理完成")

def upload_audio(file_path):
    if not os.path.exists(file_path):
        print_status(f"错误：文件 {file_path} 不存在")
        return None

    try:
        with open(file_path, 'rb') as audio_file:
            headers = {
                'Content-Type': 'audio/wav',
                'X-API-Key': SERVER_API_KEY
            }
            print_status(f"正在上传文件到 {API_URL}")
            response = requests.post(API_URL, data=audio_file, headers=headers)
        
        if response.status_code == 200:
            print_status("文件上传成功")
            result = response.json()
            print_status(f"服务器响应: {result}")
            if 'file_url' in result:
                audio_url = result['file_url']
                print_status(f"服务器返回的音频URL: {audio_url}")
                return audio_url
            else:
                print_status("警告：服务器响应中没有 file_url 字段")
        elif response.status_code == 401:
            print_status("上传失败：无效的 API 密钥")
        else:
            print_status(f"上传失败，状态码: {response.status_code}")
            print_status(f"服务器响应: {response.text}")
        return None
    except requests.RequestException as e:
        print_status(f"上传过程中发生错误: {e}")
        return None

def submit_transcription_task(file_url):
    try:
        task_response = Transcription.async_call(
            model='paraformer-v2',
            file_urls=[file_url],
            language_hints=['zh', 'en']
        )
        print_status(f"转录任务提交成功，任务ID: {task_response.output.task_id}")
        return task_response.output.task_id
    except Exception as e:
        print_status(f"提交转录任务时发生错误: {e}")
        return None

def fetch_transcription_result(task_id):
    try:
        return Transcription.fetch(task=task_id)
    except Exception as e:
        print_status(f"获取转录结果时发生错误: {e}")
        return None

def poll_transcription_task(task_id, max_attempts=30, interval=2):
    for attempt in range(max_attempts):
        response = fetch_transcription_result(task_id)
        if response:
            status = response.output.task_status
            print_status(f"尝试 {attempt + 1}: 任务状态 - {status}")
            if status in ['SUCCEEDED', 'FAILED']:
                return response
        else:
            print_status(f"尝试 {attempt + 1}: 获取任务状态失败")
        time.sleep(interval)
    print_status("任务轮询超时")
    return None

def get_detailed_transcription(transcription_url):
    try:
        response = requests.get(transcription_url)
        if response.status_code == 200:
            print_status("成功获取详细转录结果")
            return response.json()
        else:
            print_status(f"获取详细转录失败。状态码: {response.status_code}")
            return None
    except Exception as e:
        print_status(f"获取详细转录时发生错误: {e}")
        return None

def display_transcription_result(detailed_result):
    print_status("\n详细转录结果:")
    print_status(f"文件 URL: {detailed_result['file_url']}")
    print_status(f"音频格式: {detailed_result['properties']['audio_format']}")
    print_status(f"采样率: {detailed_result['properties']['original_sampling_rate']} Hz")
    print_status(f"时长: {detailed_result['properties']['original_duration_in_milliseconds']} ms")
    
    for transcript in detailed_result['transcripts']:
        print_status(f"\n通道 ID: {transcript['channel_id']}")
        print_status(f"内容时长: {transcript['content_duration_in_milliseconds']} ms")
        print_status(f"完整文本: {transcript['text']}")
        
        print_status("\n句子:")
        for sentence in transcript['sentences']:
            print_status(f"  {sentence['begin_time']} - {sentence['end_time']} ms: {sentence['text']}")
            
            print_status("  词:")
            for word in sentence['words']:
                print_status(f"    {word['begin_time']} - {word['end_time']} ms: {word['text']}{word['punctuation']}")

def main():
    global elapsed_time
    
    update_gui()
    print_status("程序初始化完成，等待用户操作")

    # 主循环
    while True:
        if is_recording:
            current_time = time.time()
            new_elapsed_time = int(current_time - recording_start_time)
            if new_elapsed_time != elapsed_time:
                elapsed_time = new_elapsed_time
                print_status(f"录音进行中，已录制 {elapsed_time} 秒")
                update_time_text()
        time.sleep(0.1)  # 小延迟以减少 CPU 使用

if __name__ == "__main__":
    main()
