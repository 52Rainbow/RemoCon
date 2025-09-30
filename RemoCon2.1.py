import socket
import os
import time
import threading
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox, simpledialog, ttk
import webbrowser
import netifaces  # 用于局域网搜索
import queue
import json
import concurrent.futures  # 用于并行扫描
from PIL import Image, ImageTk, UnidentifiedImageError  # 用于图像处理和错误捕获
import io

# 软件介绍和链接设置
SOFTWARE_INFO = """
RemoCon远程控制器 v2.1

由辞梦独立开发，基于Python的远程控制工具，支持以下功能：
- 远程命令执行
- 文件传输
- 输入设备锁定/解锁
- 网络连接控制
- 弹窗消息发送
- 系统管理命令预设
- 屏幕监控功能（支持分辨率选择和窗口调整）
- 局域网自动搜索连接
- 多设备管理与快速切换

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

# 设备数据文件路径
DEVICES_FILE = "saved_devices.json"
# 最大并行扫描线程数
MAX_SCAN_THREADS = 50
# 扫描超时时间（秒）
SCAN_TIMEOUT = 0.3

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
        self.root.geometry("1100x700")
        self.root.resizable(True, True)
        
        self.client_socket = None
        self.connected = False
        self.target_ip = tk.StringVar(value="127.0.0.1")
        self.target_port = tk.StringVar(value="9999")
        self.MESSAGE_SEPARATOR = "|||__SEP__|||"
        
        # 多设备管理相关变量
        self.devices = []  # 存储设备信息的列表
        self.current_device = None  # 当前连接的设备
        self.scanning = False  # 是否正在扫描
        self.device_groups = {"默认分组": []}  # 设备分组
        self.current_group = tk.StringVar(value="默认分组")
        
        # 屏幕监控相关变量
        self.monitoring = False
        self.monitor_window = None
        self.image_queue = queue.Queue(maxsize=5)  # 限制队列大小为5，防止内存溢出
        self.screen_width, self.screen_height = RESOLUTION_PRESETS[DEFAULT_RESOLUTION_INDEX]
        self.fps = DEFAULT_FPS
        self.quality = DEFAULT_QUALITY
        self.delay = DEFAULT_DELAY
        self.window_scale = 1.0  # 窗口缩放比例
        
        # 加载保存的设备
        self.load_devices()
        
        # 创建UI
        self.create_ui()
        
    def create_ui(self):
        """创建用户界面"""
        # 创建主框架，分为设备列表和主操作区
        main_frame = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 左侧设备管理面板
        device_frame = tk.LabelFrame(main_frame, text="设备管理", padx=5, pady=5)
        main_frame.add(device_frame, width=250, minsize=200)
        
        # 分组选择
        group_frame = tk.Frame(device_frame)
        group_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(group_frame, text="分组:").pack(side=tk.LEFT, padx=5)
        self.group_combobox = ttk.Combobox(group_frame, textvariable=self.current_group, state="readonly")
        self.group_combobox['values'] = list(self.device_groups.keys())
        self.group_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.group_combobox.bind("<<ComboboxSelected>>", self.on_group_changed)
        
        # 分组操作按钮
        group_ops_frame = tk.Frame(device_frame)
        group_ops_frame.pack(fill=tk.X, padx=5, pady=2)
        
        tk.Button(group_ops_frame, text="新建分组", command=self.create_new_group, width=10).pack(side=tk.LEFT, padx=2)
        tk.Button(group_ops_frame, text="删除分组", command=self.delete_group, width=10).pack(side=tk.LEFT, padx=2)
        
        # 设备列表
        tk.Label(device_frame, text="设备列表:").pack(anchor=tk.W, padx=5, pady=5)
        
        self.device_listbox = tk.Listbox(device_frame, selectmode=tk.SINGLE)
        self.device_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        self.device_listbox.bind('<<ListboxSelect>>', self.on_device_selected)
        
        # 设备操作按钮
        device_ops_frame = tk.Frame(device_frame)
        device_ops_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Button(device_ops_frame, text="添加设备", command=self.add_device, width=10).pack(side=tk.LEFT, padx=2)
        tk.Button(device_ops_frame, text="编辑设备", command=self.edit_device, width=10).pack(side=tk.LEFT, padx=2)
        tk.Button(device_ops_frame, text="删除设备", command=self.delete_device, width=10).pack(side=tk.LEFT, padx=2)
        
        # 扫描进度
        self.scan_progress = ttk.Progressbar(device_frame, orient="horizontal", length=100, mode="determinate")
        self.scan_progress.pack(fill=tk.X, padx=5, pady=2)
        self.scan_status = tk.Label(device_frame, text="就绪", font=("SimHei", 8))
        self.scan_status.pack(anchor=tk.W, padx=5, pady=2)
        
        # 右侧主操作区
        right_frame = tk.Frame(main_frame)
        # 修复：PanedWindow的add方法不支持weight参数，使用stretch参数替代
        main_frame.add(right_frame, stretch="always")
        
        # 连接设置区域 - 分为两行避免布局冲突
        conn_frame = tk.Frame(right_frame, padx=10, pady=5)
        conn_frame.pack(fill=tk.X)
        
        # 连接设置第一行
        conn_row1 = tk.Frame(conn_frame)
        conn_row1.pack(fill=tk.X)
        
        tk.Label(conn_row1, text="目标IP:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.ip_entry = tk.Entry(conn_row1, textvariable=self.target_ip, width=15)
        self.ip_entry.grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(conn_row1, text="端口:").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.port_entry = tk.Entry(conn_row1, textvariable=self.target_port, width=8)
        self.port_entry.grid(row=0, column=3, padx=5, pady=5)
        
        self.connect_btn = tk.Button(conn_row1, text="连接", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=4, padx=5, pady=5)
        
        # 连接设置第二行 - 放置扫描按钮，避免与grid布局冲突
        conn_row2 = tk.Frame(conn_frame)
        conn_row2.pack(fill=tk.X, pady=2)
        
        tk.Button(conn_row2, text="快速扫描", command=self.quick_scan).pack(side=tk.LEFT, padx=5, pady=2)
        tk.Button(conn_row2, text="全量扫描", command=self.full_scan).pack(side=tk.LEFT, padx=5, pady=2)
        
        tk.Button(conn_row2, text="开始监控", command=self.start_screen_monitor).pack(side=tk.LEFT, padx=5, pady=2)
        tk.Button(conn_row2, text="关于", command=self.show_about_window).pack(side=tk.LEFT, padx=5, pady=2)
        
        # 命令输入区域
        cmd_frame = tk.Frame(right_frame, padx=10, pady=5)
        cmd_frame.pack(fill=tk.X)
        
        self.cmd_entry = tk.Entry(cmd_frame)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        self.cmd_entry.bind("<Return>", lambda event: self.send_command())
        
        tk.Button(cmd_frame, text="发送命令", command=self.send_command).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(cmd_frame, text="发送文件", command=self.send_file).pack(side=tk.LEFT, padx=5, pady=5)
        
        # 功能按钮区域
        func_frame = tk.Frame(right_frame, padx=10, pady=5)
        func_frame.pack(fill=tk.X)
        
        tk.Button(func_frame, text="锁定输入设备", command=lambda: self.send_special_command("__LOCK_INPUT__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="解锁输入设备", command=lambda: self.send_special_command("__UNLOCK_INPUT__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="禁用网络", command=lambda: self.send_special_command("__disable_INTERNET__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="启用网络", command=lambda: self.send_special_command("__enable_INTERNET__")).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="发送弹窗", command=self.send_popup).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(func_frame, text="退出被控端", command=lambda: self.send_special_command("__EXIT__")).pack(side=tk.LEFT, padx=2, pady=2)
        
        # 预设命令区域
        preset_frame = tk.LabelFrame(right_frame, text="预设命令", padx=10, pady=5)
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
        result_frame = tk.Frame(right_frame, padx=10, pady=5)
        result_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(result_frame, text="输出结果:").pack(anchor=tk.W)
        self.result_text = scrolledtext.ScrolledText(result_frame, wrap=tk.WORD)
        self.result_text.pack(fill=tk.BOTH, expand=True, pady=5)
        self.result_text.config(state=tk.DISABLED)
        
        # 初始加载设备列表
        self.refresh_device_list()
    
    # 设备管理功能
    def load_devices(self):
        """从文件加载设备信息"""
        try:
            if os.path.exists(DEVICES_FILE):
                with open(DEVICES_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.devices = data.get('devices', [])
                    self.device_groups = data.get('groups', {"默认分组": []})
                    # 确保默认分组存在
                    if "默认分组" not in self.device_groups:
                        self.device_groups["默认分组"] = []
        except Exception as e:
            messagebox.showerror("错误", f"加载设备信息失败: {str(e)}")
            self.devices = []
            self.device_groups = {"默认分组": []}
    
    def save_devices(self):
        """保存设备信息到文件"""
        try:
            data = {
                'devices': self.devices,
                'groups': self.device_groups
            }
            with open(DEVICES_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("错误", f"保存设备信息失败: {str(e)}")
    
    def refresh_device_list(self):
        """刷新设备列表显示"""
        # 清空列表
        self.device_listbox.delete(0, tk.END)
        
        # 获取当前分组的设备ID
        group_device_ids = self.device_groups.get(self.current_group.get(), [])
        
        # 只显示当前分组的设备
        for device in self.devices:
            if device['id'] in group_device_ids:
                status = "在线" if device.get('online', False) else "离线"
                self.device_listbox.insert(tk.END, f"{device['name']} ({device['ip']}:{device['port']}) [{status}]")
        
        # 更新分组下拉框
        self.group_combobox['values'] = list(self.device_groups.keys())
    
    def on_group_changed(self, event=None):
        """分组变更时刷新设备列表"""
        self.refresh_device_list()
    
    def create_new_group(self):
        """创建新分组"""
        group_name = simpledialog.askstring("新建分组", "请输入分组名称:")
        if group_name and group_name not in self.device_groups:
            self.device_groups[group_name] = []
            self.current_group.set(group_name)
            self.save_devices()
            self.refresh_device_list()
    
    def delete_group(self):
        """删除当前分组"""
        current_group = self.current_group.get()
        if current_group == "默认分组":
            messagebox.showwarning("警告", "默认分组不能删除")
            return
        
        if current_group in self.device_groups:
            # 将设备移动到默认分组
            device_ids = self.device_groups[current_group]
            self.device_groups["默认分组"].extend(device_ids)
            
            # 删除分组
            del self.device_groups[current_group]
            self.current_group.set("默认分组")
            self.save_devices()
            self.refresh_device_list()
    
    def add_device(self):
        """添加新设备"""
        # 创建对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("添加设备")
        dialog.geometry("300x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 设备名称
        tk.Label(dialog, text="设备名称:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        name_var = tk.StringVar(value="新设备")
        tk.Entry(dialog, textvariable=name_var).grid(row=0, column=1, padx=5, pady=5)
        
        # IP地址
        tk.Label(dialog, text="IP地址:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        ip_var = tk.StringVar(value=self.target_ip.get())
        tk.Entry(dialog, textvariable=ip_var).grid(row=1, column=1, padx=5, pady=5)
        
        # 端口
        tk.Label(dialog, text="端口:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        port_var = tk.StringVar(value=self.target_port.get())
        tk.Entry(dialog, textvariable=port_var).grid(row=2, column=1, padx=5, pady=5)
        
        # 分组
        tk.Label(dialog, text="分组:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        group_var = tk.StringVar(value=self.current_group.get())
        group_combobox = ttk.Combobox(dialog, textvariable=group_var, state="readonly")
        group_combobox['values'] = list(self.device_groups.keys())
        group_combobox.grid(row=3, column=1, padx=5, pady=5)
        
        # 确认按钮
        def confirm():
            name = name_var.get().strip()
            ip = ip_var.get().strip()
            port = port_var.get().strip()
            group = group_var.get()
            
            if not name or not ip or not port:
                messagebox.showerror("错误", "请填写完整信息")
                return
                
            try:
                port = int(port)
                if port < 1 or port > 65535:
                    raise ValueError
            except ValueError:
                messagebox.showerror("错误", "端口必须是1-65535之间的整数")
                return
            
            # 生成唯一ID
            device_id = str(time.time()).replace('.', '')
            
            # 添加设备
            self.devices.append({
                'id': device_id,
                'name': name,
                'ip': ip,
                'port': port,
                'online': False
            })
            
            # 添加到分组
            if group not in self.device_groups:
                self.device_groups[group] = []
            self.device_groups[group].append(device_id)
            
            self.save_devices()
            self.refresh_device_list()
            dialog.destroy()
        
        tk.Button(dialog, text="确认", command=confirm).grid(row=4, column=0, padx=5, pady=10)
        tk.Button(dialog, text="取消", command=dialog.destroy).grid(row=4, column=1, padx=5, pady=10)
    
    def edit_device(self):
        """编辑选中的设备"""
        selected = self.device_listbox.curselection()
        if not selected:
            messagebox.showwarning("警告", "请先选择一个设备")
            return
        
        index = selected[0]
        current_group = self.current_group.get()
        device_ids = self.device_groups.get(current_group, [])
        
        if index >= len(device_ids):
            messagebox.showerror("错误", "无法找到选中的设备")
            return
            
        device_id = device_ids[index]
        # 查找设备
        device = next((d for d in self.devices if d['id'] == device_id), None)
        if not device:
            messagebox.showerror("错误", "无法找到选中的设备")
            return
        
        # 创建对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑设备")
        dialog.geometry("300x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 设备名称
        tk.Label(dialog, text="设备名称:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        name_var = tk.StringVar(value=device['name'])
        tk.Entry(dialog, textvariable=name_var).grid(row=0, column=1, padx=5, pady=5)
        
        # IP地址
        tk.Label(dialog, text="IP地址:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        ip_var = tk.StringVar(value=device['ip'])
        tk.Entry(dialog, textvariable=ip_var).grid(row=1, column=1, padx=5, pady=5)
        
        # 端口
        tk.Label(dialog, text="端口:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        port_var = tk.StringVar(value=str(device['port']))
        tk.Entry(dialog, textvariable=port_var).grid(row=2, column=1, padx=5, pady=5)
        
        # 分组
        tk.Label(dialog, text="分组:").grid(row=3, column=0, padx=5, pady=5, sticky=tk.W)
        group_var = tk.StringVar()
        # 找到设备当前所在的分组
        current_device_group = next((g for g, ids in self.device_groups.items() if device_id in ids), "默认分组")
        group_var.set(current_device_group)
        group_combobox = ttk.Combobox(dialog, textvariable=group_var, state="readonly")
        group_combobox['values'] = list(self.device_groups.keys())
        group_combobox.grid(row=3, column=1, padx=5, pady=5)
        
        # 确认按钮
        def confirm():
            name = name_var.get().strip()
            ip = ip_var.get().strip()
            port = port_var.get().strip()
            new_group = group_var.get()
            
            if not name or not ip or not port:
                messagebox.showerror("错误", "请填写完整信息")
                return
                
            try:
                port = int(port)
                if port < 1 or port > 65535:
                    raise ValueError
            except ValueError:
                messagebox.showerror("错误", "端口必须是1-65535之间的整数")
                return
            
            # 更新设备信息
            device['name'] = name
            device['ip'] = ip
            device['port'] = port
            
            # 如果分组变更，更新分组信息
            if new_group != current_device_group:
                # 从旧分组移除
                if current_device_group in self.device_groups and device_id in self.device_groups[current_device_group]:
                    self.device_groups[current_device_group].remove(device_id)
                # 添加到新分组
                if new_group not in self.device_groups:
                    self.device_groups[new_group] = []
                self.device_groups[new_group].append(device_id)
            
            self.save_devices()
            self.refresh_device_list()
            dialog.destroy()
        
        tk.Button(dialog, text="确认", command=confirm).grid(row=4, column=0, padx=5, pady=10)
        tk.Button(dialog, text="取消", command=dialog.destroy).grid(row=4, column=1, padx=5, pady=10)
    
    def delete_device(self):
        """删除选中的设备"""
        selected = self.device_listbox.curselection()
        if not selected:
            messagebox.showwarning("警告", "请先选择一个设备")
            return
        
        index = selected[0]
        current_group = self.current_group.get()
        device_ids = self.device_groups.get(current_group, [])
        
        if index >= len(device_ids):
            messagebox.showerror("错误", "无法找到选中的设备")
            return
            
        device_id = device_ids[index]
        # 从设备列表中删除
        self.devices = [d for d in self.devices if d['id'] != device_id]
        # 从分组中删除
        self.device_groups[current_group].remove(device_id)
        
        self.save_devices()
        self.refresh_device_list()
    
    def on_device_selected(self, event=None):
        """选中设备时更新IP和端口输入框"""
        selected = self.device_listbox.curselection()
        if not selected:
            return
        
        index = selected[0]
        current_group = self.current_group.get()
        device_ids = self.device_groups.get(current_group, [])
        
        if index >= len(device_ids):
            return
            
        device_id = device_ids[index]
        device = next((d for d in self.devices if d['id'] == device_id), None)
        if device:
            self.target_ip.set(device['ip'])
            self.target_port.set(str(device['port']))
            self.current_device = device
    
    def check_device_status(self):
        """检查所有设备的在线状态"""
        def check_status(device):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.2)
                result = sock.connect_ex((device['ip'], int(device['port'])))
                sock.close()
                return result == 0
            except:
                return False
        
        # 使用线程池并行检查设备状态
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # 创建一个字典映射设备到其检查任务
            future_to_device = {executor.submit(check_status, device): device for device in self.devices}
            
            for future in concurrent.futures.as_completed(future_to_device):
                device = future_to_device[future]
                try:
                    device['online'] = future.result()
                except:
                    device['online'] = False
        
        self.refresh_device_list()
    
    # 优化的局域网扫描功能
    def quick_scan(self):
        """快速扫描常见网段，只扫描可能的IP"""
        self.start_scan(quick=True)
    
    def full_scan(self):
        """全量扫描所有可能的IP"""
        self.start_scan(quick=False)
    
    def start_scan(self, quick=True):
        """开始扫描局域网设备"""
        if self.scanning:
            messagebox.showinfo("提示", "正在扫描中，请等待完成")
            return
            
        if self.connected:
            messagebox.showinfo("提示", "已处于连接状态，扫描可能影响连接稳定性")
        
        self.append_result("开始扫描局域网内的被控端...")
        self.scanning = True
        self.scan_progress["value"] = 0
        self.scan_status.config(text="正在获取网络信息...")
        
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
            self.scanning = False
            self.scan_status.config(text="就绪")
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
            
            if quick:
                # 快速扫描：只扫描常见IP段
                ip_ranges.append(f"{base_ip}.1-50")
                ip_ranges.append(f"{base_ip}.100-150")
                ip_ranges.append(f"{base_ip}.200-254")
            else:
                # 全量扫描：扫描所有可能IP
                ip_ranges.append(f"{base_ip}.1-254")
        
        # 启动扫描线程
        threading.Thread(target=self.perform_scan, args=(ip_ranges, quick), daemon=True).start()
    
    def perform_scan(self, ip_ranges, quick):
        """执行扫描操作"""
        port = int(self.target_port.get())
        found_devices = []
        total_ips = 0
        scanned_ips = 0
        
        # 先计算总IP数量
        for ip_range in ip_ranges:
            base = ip_range.split('-')[0].rsplit('.', 1)[0]
            start, end = map(int, ip_range.split('-')[1].split('.')) if '.' in ip_range.split('-')[1] else (1, 255)
            total_ips += end - start + 1
        
        # 使用线程池并行扫描
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_SCAN_THREADS) as executor:
            # 创建扫描任务
            futures = []
            
            for ip_range in ip_ranges:
                base = ip_range.split('-')[0].rsplit('.', 1)[0]
                range_part = ip_range.split('-')[1]
                if '.' in range_part:
                    start, end = map(int, range_part.split('.'))
                else:
                    start = int(range_part.split('-')[0]) if '-' in range_part else 1
                    end = int(range_part.split('-')[1]) if '-' in range_part else 255
                
                for i in range(start, end + 1):
                    ip = f"{base}.{i}"
                    futures.append(executor.submit(self.test_connection, ip, port))
            
            # 处理扫描结果
            for future in concurrent.futures.as_completed(futures):
                if not self.scanning:  # 如果用户终止了扫描
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                    
                result = future.result()
                scanned_ips += 1
                
                # 更新进度
                progress = (scanned_ips / total_ips) * 100
                self.scan_progress["value"] = progress
                self.scan_status.config(text=f"已扫描 {scanned_ips}/{total_ips} 个IP，发现 {len(found_devices)} 个设备")
                
                if result:
                    ip, port = result
                    found_devices.append((ip, port))
                    self.append_result(f"发现被控端: {ip}:{port}")
        
        # 扫描完成
        self.scanning = False
        self.scan_progress["value"] = 100
        self.scan_status.config(text="扫描完成")
        
        if found_devices:
            self.append_result(f"扫描完成，共发现 {len(found_devices)} 个被控端")
            
            # 询问是否添加发现的设备
            if messagebox.askyesno("添加设备", f"发现 {len(found_devices)} 个被控端，是否添加到设备列表?"):
                for ip, port in found_devices:
                    # 检查是否已存在
                    exists = any(d['ip'] == ip and d['port'] == port for d in self.devices)
                    if not exists:
                        # 生成唯一ID
                        device_id = str(time.time()).replace('.', '') + str(port)
                        
                        # 添加设备
                        self.devices.append({
                            'id': device_id,
                            'name': f"自动添加_{ip.split('.')[-1]}",
                            'ip': ip,
                            'port': port,
                            'online': True
                        })
                        
                        # 添加到当前分组
                        current_group = self.current_group.get()
                        if current_group not in self.device_groups:
                            self.device_groups[current_group] = []
                        self.device_groups[current_group].append(device_id)
                
                self.save_devices()
                self.refresh_device_list()
        else:
            self.append_result("扫描完成，未发现可用的被控端")
    
    def test_connection(self, ip, port):
        """测试与指定IP和端口的连接"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SCAN_TIMEOUT)
            result = sock.connect_ex((ip, port))
            sock.close()
            if result == 0:
                return (ip, port)
            return None
        except Exception as e:
            return None
    
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
            
            # 更新设备在线状态
            for device in self.devices:
                if device['ip'] == ip and str(device['port']) == str(port):
                    device['online'] = True
            self.refresh_device_list()
            
            # 启动接收线程
            self.receive_thread = threading.Thread(target=self.receive_data, daemon=True)
            self.receive_thread.start()
            
        except Exception as e:
            self.append_result(f"连接失败: {str(e)}")
            # 更新设备在线状态
            for device in self.devices:
                if device['ip'] == ip and str(device['port']) == str(port):
                    device['online'] = False
            self.refresh_device_list()
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
            
            # 更新设备在线状态
            if self.current_device:
                self.current_device['online'] = False
                self.refresh_device_list()
                
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
    