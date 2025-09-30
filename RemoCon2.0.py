import socket
import os
import time
import threading
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox, simpledialog, ttk
import webbrowser
import netifaces  # 用于局域网搜索
import queue
from PIL import Image, ImageTk, UnidentifiedImageError  # 用于图像处理和错误捕获
import io

# 软件介绍和链接设置
SOFTWARE_INFO = """
RemoCon远程控制器 v2.0

由辞梦独立开发，基于Python的远程控制工具，支持以下功能：
- 远程命令执行
- 文件传输
- 输入设备锁定/解锁
- 网络连接控制
- 弹窗消息发送
- 系统管理命令预设
- 屏幕监控功能（支持分辨率选择和窗口调整）
- 局域网自动搜索连接

声明：
该项目为开源项目，仅供参考学习，使用者行为与开发者无关。
使用前请确保已获得被控设备的授权，
遵守相关法律法规和隐私政策。
请勿用于违法用途。
"""
AUTHOR_BLOG_URL = "https://cimeng.netlify.app/"  # 作者博客地址
GITHUB_PROJECT_URL = "https://github.com/52Rainbow/RemoCon"  # GitHub项目地址

# 屏幕监控预设分辨率
RESOLUTION_PRESETS = [
    (640, 480),    # 标清
    (800, 600),    # 普清
    (1024, 768),   # XGA
    (1280, 720),   # HD
    (1280, 1024),  # SXGA
    (1920, 1080)   # FHD
]

# 屏幕监控默认参数
DEFAULT_RESOLUTION_INDEX = 3  # 默认使用1280x720
DEFAULT_FPS = 10
DEFAULT_QUALITY = 50  # 中等质量（0-100）
DEFAULT_DELAY = 0.5
IMAGE_MAGIC_NUMBER = b"IMGB"  # 图像数据开头的魔术数字，用于识别
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 最大图像大小限制（10MB）

class RemoteController:
    def __init__(self, root):
        self.root = root
        self.root.title("远程控制器")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        self.client_socket = None
        self.connected = False
        self.target_ip = tk.StringVar(value="127.0.0.1")
        self.target_port = tk.StringVar(value="9999")
        self.MESSAGE_SEPARATOR = "|||__SEP__|||"
        
        # 屏幕监控相关变量
        self.monitoring = False
        self.monitor_window = None
        self.image_queue = queue.Queue(maxsize=5)  # 限制队列大小为5，防止内存溢出
        self.screen_width, self.screen_height = RESOLUTION_PRESETS[DEFAULT_RESOLUTION_INDEX]
        self.fps = DEFAULT_FPS
        self.quality = DEFAULT_QUALITY
        self.delay = DEFAULT_DELAY
        self.window_scale = 1.0  # 窗口缩放比例
        
        # 创建UI
        self.create_ui()
        
    def create_ui(self):
        """创建用户界面"""
        # 连接设置区域
        conn_frame = tk.Frame(self.root, padx=10, pady=5)
        conn_frame.pack(fill=tk.X)
        
        tk.Label(conn_frame, text="目标IP:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        tk.Entry(conn_frame, textvariable=self.target_ip, width=15).grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(conn_frame, text="端口:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        tk.Entry(conn_frame, textvariable=self.target_port, width=8).grid(row=0, column=3, padx=5, pady=5)
        
        self.connect_btn = tk.Button(conn_frame, text="连接", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=4, padx=5, pady=5)
        
        # 自动连接按钮
        tk.Button(conn_frame, text="自动连接", command=self.auto_connect).grid(row=0, column=5, padx=5, pady=5)
        
        # 屏幕监控按钮
        tk.Button(conn_frame, text="开始监控", command=self.start_screen_monitor).grid(row=0, column=6, padx=5, pady=5)
        
        # 关于按钮
        tk.Button(conn_frame, text="关于", command=self.show_about_window).grid(row=0, column=7, padx=5, pady=5)
        
        # 命令输入区域
        cmd_frame = tk.Frame(self.root, padx=10, pady=5)
        cmd_frame.pack(fill=tk.X)
        
        self.cmd_entry = tk.Entry(cmd_frame)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        self.cmd_entry.bind("<Return>", lambda event: self.send_command())
        
        tk.Button(cmd_frame, text="发送命令", command=self.send_command).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(cmd_frame, text="发送文件", command=self.send_file).pack(side=tk.LEFT, padx=5, pady=5)
        
        # 功能按钮区域
        func_frame = tk.Frame(self.root, padx=10, pady=5)
        func_frame.pack(fill=tk.X)
        
        tk.Button(func_frame, text="锁定输入设备", command=lambda: self.send_special_command("__LOCK_INPUT__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="解锁输入设备", command=lambda: self.send_special_command("__UNLOCK_INPUT__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="禁用网络", command=lambda: self.send_special_command("__disable_INTERNET__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="启用网络", command=lambda: self.send_special_command("__enable_INTERNET__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="发送弹窗", command=self.send_popup).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="退出被控端", command=lambda: self.send_special_command("__EXIT__")).pack(side=tk.LEFT, padx=2, pady=2)
        
        # 预设命令区域
        preset_frame = tk.LabelFrame(self.root, text="预设命令", padx=10, pady=5)
        preset_frame.pack(fill=tk.X, padx=10, pady=5)
        
        presets = [
            ("查看系统信息", "systeminfo"),
            ("查看IP配置", "ipconfig /all"),
            ("查看进程列表", "tasklist"),
            ("查看服务列表", "net start"),
            ("查看目录内容", "dir"),
            ("查看用户列表", "net user"),
            ("关闭计算机", "shutdown /s /t 60"),
            ("重启计算机", "shutdown /r /t 60"),
            ("取消关机", "shutdown /a"),
            ("清除事件日志", "wevtutil cl System")
        ]
        
        for i, (text, cmd) in enumerate(presets):
            btn = tk.Button(preset_frame, text=text, 
                          command=lambda c=cmd: self.send_preset_command(c))
            btn.grid(row=i//5, column=i%5, padx=5, pady=5, sticky="ew")
        
        for i in range(2):
            preset_frame.grid_rowconfigure(i, weight=1)
        for i in range(5):
            preset_frame.grid_columnconfigure(i, weight=1)
        
        # 结果显示区域
        result_frame = tk.Frame(self.root, padx=10, pady=5)
        result_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(result_frame, text="输出结果:").pack(anchor=tk.W)
        self.result_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD)
        self.result_text.pack(fill=tk.BOTH, expand=True, pady=5)
        self.result_text.config(state=tk.DISABLED)
    
    # 自动连接功能
    def auto_connect(self):
        """自动搜索局域网内的被控端并连接"""
        if self.connected:
            messagebox.showinfo("提示", "已处于连接状态")
            return
            
        self.append_result("开始搜索局域网内的被控端...")
        
        # 获取本机IP和子网
        local_ips = []
        for interface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(interface)
            if netifaces.AF_INET in addrs:
                for addr_info in addrs[netifaces.AF_INET]:
                    ip = addr_info['addr']
                    netmask = addr_info['netmask']
                    if not ip.startswith("127."):  # 排除本地回环地址
                        local_ips.append((ip, netmask))
        
        if not local_ips:
            self.append_result("无法获取本机网络信息")
            return
        
        # 生成IP扫描范围
        ip_ranges = []
        for ip, netmask in local_ips:
            ip_parts = list(map(int, ip.split('.')))
            mask_parts = list(map(int, netmask.split('.')))
            
            # 计算网络地址
            network_parts = [i & m for i, m in zip(ip_parts, mask_parts)]
            network = ".".join(map(str, network_parts))
            
            # 生成IP范围
            base_ip = ".".join(network.split('.')[:3])
            ip_ranges.append(f"{base_ip}.1-255")
        
        # 扫描线程
        def scan_thread():
            port = int(self.target_port.get())
            found = False
            
            for ip_range in ip_ranges:
                base = ip_range.split('-')[0].rsplit('.', 1)[0]
                start, end = map(int, ip_range.split('-')[1].split('.')) if '.' in ip_range.split('-')[1] else (1, 255)
                
                for i in range(start, end + 1):
                    if found:
                        break
                        
                    ip = f"{base}.{i}"
                    self.append_result(f"正在尝试连接 {ip}:{port}")
                    
                    try:
                        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        test_socket.settimeout(0.5)
                        result = test_socket.connect_ex((ip, port))
                        test_socket.close()
                        
                        if result == 0:
                            self.append_result(f"发现被控端: {ip}:{port}")
                            self.target_ip.set(ip)
                            self.connect_to_server()
                            found = True
                            break
                    except Exception as e:
                        continue
            
            if not found:
                self.append_result("未找到可用的被控端")
        
        # 启动扫描线程
        threading.Thread(target=scan_thread, daemon=True).start()
    
    # 屏幕监控窗口
    def start_screen_monitor(self):
        """打开屏幕监控窗口"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
            
        if self.monitoring:
            messagebox.showinfo("提示", "监控已在运行中")
            return
            
        # 创建监控窗口
        self.monitor_window = tk.Toplevel(self.root)
        self.monitor_window.title("屏幕监控")
        # 初始窗口大小基于所选分辨率
        init_width = int(self.screen_width + 200)
        init_height = int(self.screen_height + 100)
        self.monitor_window.geometry(f"{init_width}x{init_height}")
        self.monitor_window.resizable(True, True)  # 允许调整窗口大小
        self.monitor_window.protocol("WM_DELETE_WINDOW", self.stop_screen_monitor)
        
        # 绑定窗口大小变化事件
        self.monitor_window.bind("<Configure>", self.on_window_resize)
        
        # 参数设置区域
        params_frame = tk.LabelFrame(self.monitor_window, text="监控参数")
        params_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        
        # 分辨率预设选择
        tk.Label(params_frame, text="分辨率预设:").pack(anchor=tk.W, padx=5, pady=2)
        self.resolution_var = tk.StringVar()
        # 找到当前分辨率在预设列表中的索引
        current_res_index = next((i for i, (w, h) in enumerate(RESOLUTION_PRESETS) 
                                if w == self.screen_width and h == self.screen_height), 
                                DEFAULT_RESOLUTION_INDEX)
        self.resolution_var.set(f"{RESOLUTION_PRESETS[current_res_index][0]}x{RESOLUTION_PRESETS[current_res_index][1]}")
        
        resolution_menu = tk.OptionMenu(params_frame, self.resolution_var, 
                                       *[f"{w}x{h}" for w, h in RESOLUTION_PRESETS])
        resolution_menu.pack(fill=tk.X, padx=5, pady=2)
        
        # FPS设置
        tk.Label(params_frame, text="帧率(FPS):").pack(anchor=tk.W, padx=5, pady=2)
        self.fps_var = tk.IntVar(value=self.fps)
        self.fps_scale = tk.Scale(params_frame, from_=1, to=15, orient=tk.HORIZONTAL, 
                           variable=self.fps_var, length=150)  # 最大FPS限制为15
        self.fps_scale.pack(fill=tk.X, padx=5, pady=2)
        
        # 质量设置
        tk.Label(params_frame, text="质量(0-100):").pack(anchor=tk.W, padx=5, pady=2)
        self.quality_var = tk.IntVar(value=self.quality)
        self.quality_scale = tk.Scale(params_frame, from_=10, to=80, orient=tk.HORIZONTAL, 
                               variable=self.quality_var, length=150)  # 质量范围缩小
        self.quality_scale.pack(fill=tk.X, padx=5, pady=2)
        
        # 延迟设置
        tk.Label(params_frame, text="延迟(秒):").pack(anchor=tk.W, padx=5, pady=2)
        self.delay_var = tk.DoubleVar(value=self.delay)
        self.delay_scale = tk.Scale(params_frame, from_=0.2, to=2.0, resolution=0.1, orient=tk.HORIZONTAL, 
                             variable=self.delay_var, length=150)
        self.delay_scale.pack(fill=tk.X, padx=5, pady=2)
        
        # 应用按钮
        def apply_settings():
            try:
                # 从预设中获取分辨率
                res_str = self.resolution_var.get()
                width, height = map(int, res_str.split('x'))
                
                fps = self.fps_var.get()
                quality = self.quality_var.get()
                delay = self.delay_var.get()
                
                # 验证参数有效性
                if width <= 0 or height <= 0:
                    raise ValueError("分辨率必须为正数")
                if fps <= 0 or fps > 15:
                    raise ValueError("帧率必须在1-15之间")
                if quality <= 0 or quality > 100:
                    raise ValueError("质量必须在1-100之间")
                if delay < 0.2 or delay > 2.0:
                    raise ValueError("延迟必须在0.2-2.0秒之间")
                
                self.screen_width = width
                self.screen_height = height
                self.fps = fps
                self.quality = quality
                self.delay = delay
                
                # 重置窗口缩放比例
                self.window_scale = 1.0
                
                # 如果正在监控，重新启动以应用新参数
                if self.monitoring:
                    self.stop_screen_monitor(restart=True)
                
            except ValueError as e:
                messagebox.showerror("错误", f"参数无效: {str(e)}")
        
        tk.Button(params_frame, text="应用设置", command=apply_settings).pack(pady=10)
        tk.Button(params_frame, text="停止监控", command=self.stop_screen_monitor).pack(pady=5)
        
        # 当前窗口大小显示
        self.window_size_label = tk.Label(params_frame, text=f"窗口大小: {self.screen_width}x{self.screen_height}")
        self.window_size_label.pack(pady=10)
        
        # 监控画面区域
        monitor_frame = tk.Frame(self.monitor_window)
        monitor_frame.pack(side=tk.LEFT, padx=10, pady=10, fill=tk.BOTH, expand=True)
        
        self.monitor_label = tk.Label(monitor_frame)
        self.monitor_label.pack(fill=tk.BOTH, expand=True)
        
        # 创建初始空白图像
        self.blank_image = Image.new('RGB', (self.screen_width, self.screen_height), color='black')
        self.blank_photo = ImageTk.PhotoImage(image=self.blank_image)
        self.monitor_label.config(image=self.blank_photo)
        self.monitor_label.image = self.blank_photo  # 保持引用
        
        # 启动监控
        self.monitoring = True
        self.send_start_monitor_command()
        
        # 启动画面更新线程
        self.receive_thread = threading.Thread(target=self.receive_screen_data, daemon=True)
        self.receive_thread.start()
        self.update_monitor_display()
    
    def on_window_resize(self, event):
        """窗口大小改变时的处理"""
        if not self.monitor_window or not self.monitoring:
            return
            
        # 只处理用户主动调整大小的事件，忽略程序触发的
        if event.widget == self.monitor_window and event.width > 100 and event.height > 100:
            # 计算新的缩放比例（减去参数面板的宽度）
            available_width = event.width - 220  # 减去参数面板宽度和边距
            available_height = event.height - 40  # 减去边距
            
            # 计算基于宽度和高度的缩放比例，取较小值以保持比例
            scale_width = available_width / self.screen_width
            scale_height = available_height / self.screen_height
            self.window_scale = min(scale_width, scale_height)
            
            # 更新窗口大小标签
            scaled_width = int(self.screen_width * self.window_scale)
            scaled_height = int(self.screen_height * self.window_scale)
            self.window_size_label.config(text=f"窗口大小: {scaled_width}x{scaled_height}")
    
    def send_start_monitor_command(self):
        """发送开始监控命令"""
        try:
            command = f"__START_MONITOR__{self.MESSAGE_SEPARATOR}{self.screen_width}{self.MESSAGE_SEPARATOR}{self.screen_height}{self.MESSAGE_SEPARATOR}{self.fps}{self.MESSAGE_SEPARATOR}{self.quality}{self.MESSAGE_SEPARATOR}{self.delay}"
            self.client_socket.sendall(command.encode('utf-8'))
            self.append_result(f"已发送开始监控命令，参数: {self.screen_width}x{self.screen_height}, {self.fps}FPS, 质量{self.quality}, 延迟{self.delay}s")
        except Exception as e:
            self.append_result(f"发送监控命令失败: {str(e)}")
            self.stop_screen_monitor()
    
    def receive_screen_data(self):
        """接收屏幕数据"""
        while self.monitoring and self.connected and self.client_socket:
            try:
                # 设置非阻塞模式
                self.client_socket.setblocking(False)
                
                # 尝试接收魔术数字以识别是否为图像数据
                magic = b""
                while len(magic) < len(IMAGE_MAGIC_NUMBER):
                    try:
                        chunk = self.client_socket.recv(len(IMAGE_MAGIC_NUMBER) - len(magic))
                        if not chunk:
                            break
                        magic += chunk
                    except socket.error as e:
                        # 处理非阻塞错误
                        if e.errno == 10035:  # WSAEWOULDBLOCK
                            time.sleep(0.01)  # 短暂等待后重试
                            continue
                        else:
                            raise
                
                if not magic:
                    continue
                    
                # 检查是否为图像数据
                if magic == IMAGE_MAGIC_NUMBER:
                    # 接收数据长度（4字节）
                    length_data = b""
                    while len(length_data) < 4:
                        try:
                            chunk = self.client_socket.recv(4 - len(length_data))
                            if not chunk:
                                break
                            length_data += chunk
                        except socket.error as e:
                            if e.errno == 10035:  # WSAEWOULDBLOCK
                                time.sleep(0.01)
                                continue
                            else:
                                raise
                    
                    if not length_data or len(length_data) != 4:
                        self.append_result("接收图像长度失败")
                        continue
                        
                    data_length = int.from_bytes(length_data, byteorder='big')
                    
                    # 验证数据长度是否合理
                    if data_length <= 0 or data_length > MAX_IMAGE_SIZE:
                        self.append_result(f"无效的图像数据长度: {data_length}，跳过此帧")
                        # 尝试跳过无效数据
                        remaining = data_length
                        while remaining > 0:
                            try:
                                skip = self.client_socket.recv(min(4096, remaining))
                                if not skip:
                                    break
                                remaining -= len(skip)
                            except socket.error as e:
                                if e.errno == 10035:
                                    time.sleep(0.01)
                                    continue
                                else:
                                    break
                        continue
                    
                    # 接收图像数据
                    img_data = b''
                    while len(img_data) < data_length:
                        try:
                            chunk_size = min(4096, data_length - len(img_data))
                            chunk = self.client_socket.recv(chunk_size)
                            if not chunk:
                                break
                            img_data += chunk
                        except socket.error as e:
                            if e.errno == 10035:  # WSAEWOULDBLOCK
                                time.sleep(0.01)
                                continue
                            else:
                                raise
                    
                    if len(img_data) == data_length:
                        # 清空队列中旧的图像数据，只保留最新的
                        while self.image_queue.full():
                            self.image_queue.get()
                        self.image_queue.put(img_data)
                    else:
                        self.append_result(f"图像数据接收不完整，预期 {data_length} 字节，实际 {len(img_data)} 字节，跳过此帧")
                
                else:
                    # 不是图像数据，尝试解析为文本响应
                    try:
                        # 把魔术数字部分也包含进去一起解码
                        text_data = magic
                        while True:
                            try:
                                chunk = self.client_socket.recv(4096)
                                if not chunk:
                                    break
                                text_data += chunk
                            except socket.error as e:
                                if e.errno == 10035:  # WSAEWOULDBLOCK
                                    break
                                else:
                                    raise
                        
                        text = text_data.decode('utf-8', errors='ignore')
                        if text:
                            self.append_result(f"收到: {text}")
                    except Exception as e:
                        self.append_result(f"解析文本数据失败: {str(e)}")
                
            except Exception as e:
                if self.monitoring:  # 只有在监控状态下才显示错误
                    if "10035" in str(e):
                        # 处理非阻塞错误，不中断线程
                        time.sleep(0.1)
                        continue
                    self.append_result(f"接收屏幕数据错误: {str(e)}")
                break
            finally:
                # 恢复为阻塞模式
                try:
                    self.client_socket.setblocking(True)
                except:
                    pass
    
    def update_monitor_display(self):
        """更新监控画面显示（支持窗口缩放）"""
        if not self.monitoring or not self.monitor_window:
            return
            
        try:
            while not self.image_queue.empty():
                img_data = self.image_queue.get()
                try:
                    # 尝试打开图像
                    img = Image.open(io.BytesIO(img_data))
                    
                    # 根据窗口缩放比例调整图像大小
                    if self.window_scale != 1.0:
                        new_width = int(img.width * self.window_scale)
                        new_height = int(img.height * self.window_scale)
                        img = img.resize((new_width, new_height), Image.LANCZOS)
                    
                    photo = ImageTk.PhotoImage(image=img)
                    self.monitor_label.config(image=photo)
                    self.monitor_label.image = photo  # 保持引用
                except UnidentifiedImageError:
                    self.append_result("无法识别图像数据，跳过此帧")
                except Exception as e:
                    self.append_result(f"处理图像数据失败: {str(e)}")
        except Exception as e:
            self.append_result(f"更新监控画面错误: {str(e)}")
        
        if self.monitoring and self.monitor_window:
            # 计算下一帧的更新时间
            self.monitor_window.after(int(1000/self.fps), self.update_monitor_display)
    
    def stop_screen_monitor(self, restart=False):
        """停止屏幕监控"""
        self.monitoring = False
        try:
            if self.connected and self.client_socket:
                self.client_socket.sendall("__STOP_MONITOR__".encode('utf-8'))
                self.append_result("已发送停止监控命令")
        except Exception as e:
            self.append_result(f"发送停止监控命令失败: {str(e)}")
        
        if self.monitor_window:
            self.monitor_window.destroy()
            self.monitor_window = None
        
        # 如果需要重启监控
        if restart:
            self.start_screen_monitor()
    
    def show_about_window(self):
        """显示关于窗口"""
        about_window = tk.Toplevel(self.root)
        about_window.title("关于远程控制器")
        about_window.geometry("500x400")
        about_window.resizable(False, False)
        about_window.transient(self.root)
        about_window.grab_set()
        
        text_widget = scrolledtext.ScrolledText(about_window, wrap=tk.WORD, padx=10, pady=10)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.insert(tk.END, SOFTWARE_INFO)
        text_widget.config(state=tk.DISABLED, font=("SimHei", 10))
        
        btn_frame = tk.Frame(about_window, pady=10)
        btn_frame.pack(fill=tk.X, padx=10)
        
        tk.Button(
            btn_frame, 
            text="访问作者博客", 
            command=lambda: webbrowser.open(AUTHOR_BLOG_URL)
        ).pack(side=tk.LEFT, padx=20, expand=True)
        
        tk.Button(
            btn_frame, 
            text="查看GitHub项目", 
            command=lambda: webbrowser.open(GITHUB_PROJECT_URL)
        ).pack(side=tk.RIGHT, padx=20, expand=True)
        
        tk.Button(about_window, text="关闭", command=about_window.destroy).pack(pady=10)
    
    def toggle_connection(self):
        """切换连接状态（连接/断开）"""
        if not self.connected:
            self.connect_to_server()
        else:
            self.disconnect()
    
    def connect_to_server(self):
        """连接到被控端服务器"""
        try:
            ip = self.target_ip.get()
            port = int(self.target_port.get())
            
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((ip, port))
            
            self.connected = True
            self.connect_btn.config(text="断开连接")
            self.append_result(f"已成功连接到 {ip}:{port}")
            
            # 启动接收线程
            self.receive_thread = threading.Thread(target=self.receive_data, daemon=True)
            self.receive_thread.start()
            
        except Exception as e:
            self.append_result(f"连接失败: {str(e)}")
            self.client_socket = None
    
    def disconnect(self):
        """断开与被控端的连接"""
        if self.connected and self.client_socket:
            try:
                self.client_socket.close()
            except Exception as e:
                self.append_result(f"断开连接时出错: {str(e)}")
            
            self.connected = False
            self.connect_btn.config(text="连接")
            self.append_result("已断开连接")
            self.client_socket = None
    
    def receive_data(self):
        """接收被控端返回的文本数据"""
        while self.connected and self.client_socket:
            try:
                data = self.client_socket.recv(4096).decode('utf-8', errors='ignore')
                if not data:
                    self.append_result("连接已被远程关闭")
                    self.disconnect()
                    break
                self.append_result(f"收到: {data}")
            except Exception as e:
                if self.connected:  # 只有在仍然连接的情况下才显示错误
                    self.append_result(f"接收数据出错: {str(e)}")
                break
    
    def send_command(self):
        """发送命令到被控端"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
        
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        
        try:
            self.client_socket.sendall(cmd.encode('utf-8'))
            self.append_result(f"已发送命令: {cmd}")
            self.cmd_entry.delete(0, tk.END)
        except Exception as e:
            self.append_result(f"发送命令失败: {str(e)}")
            self.disconnect()
    
    def send_preset_command(self, cmd):
        """发送预设命令"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
            
        # 在输入框中显示预设命令，方便用户查看和修改
        self.cmd_entry.delete(0, tk.END)
        self.cmd_entry.insert(0, cmd)
        
        try:
            self.client_socket.sendall(cmd.encode('utf-8'))
            self.append_result(f"已发送预设命令: {cmd}")
        except Exception as e:
            self.append_result(f"发送预设命令失败: {str(e)}")
            self.disconnect()
    
    def send_special_command(self, command):
        """发送特殊控制命令"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
        
        try:
            self.client_socket.sendall(command.encode('utf-8'))
            self.append_result(f"已发送特殊命令: {command}")
        except Exception as e:
            self.append_result(f"发送命令失败: {str(e)}")
            self.disconnect()
    
    def send_popup(self):
        """发送弹窗消息"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
        
        msg = simpledialog.askstring("输入消息", "请输入要显示的弹窗消息:")
        if msg is not None:  # 允许空消息，但要处理
            try:
                # 使用特殊分隔符，避免与消息内容中的|冲突
                command = f"__POPUP_MESSAGE__{self.MESSAGE_SEPARATOR}{msg}"
                self.client_socket.sendall(command.encode('utf-8'))
                
                # 等待确认消息
                timeout = 5
                start_time = time.time()
                self.client_socket.settimeout(1)
                
                while time.time() - start_time < timeout:
                    try:
                        response = self.client_socket.recv(1024).decode('utf-8')
                        if response:
                            self.append_result(f"弹窗响应: {response}")
                            return
                    except socket.timeout:
                        continue
                
                self.append_result(f"弹窗消息已发送，但未收到确认")
                
            except Exception as e:
                self.append_result(f"发送弹窗消息失败: {str(e)}")
                self.disconnect()
            finally:
                self.client_socket.settimeout(None)
    
    def send_file(self):
        """发送文件到被控端"""
        if not self.connected or not self.client_socket:
            messagebox.showwarning("警告", "请先建立连接")
            return
        
        file_path = filedialog.askopenfilename(title="选择要发送的文件")
        if not file_path:
            return
        
        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            # 发送文件信息
            command = f"__SEND_FILE__|{file_name}|{file_size}"
            self.client_socket.sendall(command.encode('utf-8'))
            
            # 等待被控端准备好
            time.sleep(1)
            
            # 发送文件内容
            with open(file_path, 'rb') as f:
                bytes_sent = 0
                while bytes_sent < file_size:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    self.client_socket.sendall(chunk)
                    bytes_sent += len(chunk)
            
            self.append_result(f"文件 {file_name} 发送完成，大小: {file_size} 字节")
            
        except Exception as e:
            self.append_result(f"发送文件失败: {str(e)}")
            self.disconnect()
    
    def append_result(self, text):
        """在结果区域添加文本"""
        self.result_text.config(state=tk.NORMAL)
        self.result_text.insert(tk.END, text + "\n")
        self.result_text.see(tk.END)  # 滚动到最后
        self.result_text.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    # 确保中文显示正常
    root.option_add("*Font", "SimHei 9")
    app = RemoteController(root)
    root.mainloop()
