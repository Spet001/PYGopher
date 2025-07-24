import tkinter as tk
from tkinter import ttk, messagebox
import configparser
import pygame
import pyautogui
import time
from ctypes import windll, Structure, c_long, byref
import threading
import os

# --- Configurações Globais ---
CONFIG_FILE = 'gopher_config.ini'
DEAD_ZONE = 4000  # Limiar para movimento do analógico (evita drift)
SCROLL_DEAD_ZONE = 5000 # Limiar para rolagem do analógico
FPS = 150 # Frames por segundo para o loop do controle
SLEEP_AMOUNT = 1.0 / FPS # Tempo de espera entre cada iteração do loop

# Estrutura para obter a posição do cursor do mouse (Windows API)
class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]

# --- Classe Principal da Aplicação ---
class Gopher360App:
    def __init__(self, root):
        self.root = root
        self.root.title("Gopher360 - Python")
        self.root.geometry("800x600")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing) # Garante que o thread pare ao fechar

        # Variáveis de estado da aplicação
        self.running = False
        self.disabled = False
        self.hidden = False
        self.controller_thread = None

        # Configurações de velocidade do mouse
        self.base_speed = 0.000002 # Reduzida drasticamente para testar uma sensibilidade muito baixa
        self.sensitivity_multiplier = 1.0 # Multiplicador de sensibilidade ajustável pelo usuário
        self.current_speed = self.base_speed * self.sensitivity_multiplier

        self.SPEED_LOW_MULTIPLIER = 0.5 # Multiplicador para velocidade 'Baixa'
        self.SPEED_MED_MULTIPLIER = 1.0 # Multiplicador para velocidade 'Média'
        self.SPEED_HIGH_MULTIPLIER = 2.0 # Multiplicador para velocidade 'Alta'


        # Mapeamentos padrão dos botões do controle para ações
        # IMPORTANTE: mouse_left/right/middle e outros usam os índices de botões do Pygame (0, 1, 2, etc.)
        # Outros mapeamentos (dpad_up, start, etc.) usam códigos de tecla virtuais do Windows (hex)
        self.default_mappings = {
            # Cliques do mouse (usando índices de botões do Pygame)
            'mouse_left': '0x0',    # Botão 'A' (índice 0)
            'mouse_right': '0x1',   # Botão 'B' (índice 1)
            'mouse_middle': '0x2',  # Botão 'X' (índice 2)

            # Funções do Gopher360
            'hide_window': '0x7A', # F11
            'disable_gopher': '0x24', # Home
            'speed_change': '0x21', # Page Up

            # Mapeamentos de teclas (usando códigos de tecla virtuais do Windows)
            'dpad_up': '0x26',      # Seta para cima
            'dpad_down': '0x28',    # Seta para baixo
            'dpad_left': '0x25',    # Seta para esquerda
            'dpad_right': '0x27',   # Seta para direita
            'start': '0x0D',        # Enter
            'back': '0x08',         # Backspace
            'left_thumb': '0x71',   # F2
            'right_thumb': '0x72',  # F3
            'left_shoulder': '0xA0', # Shift esquerdo
            'right_shoulder': '0xA1', # Shift direito
            'a_button': '0x0',      # Ação separada para 'A' se não for clique do mouse
            'b_button': '0x0',      # Ação separada para 'B' se não for clique do mouse
            'x_button': '0x0',      # Ação separada para 'X' se não for clique do mouse
            'y_button': '0x0',      # Ação separada para 'Y' se não for clique do mouse
            'left_trigger': '0x20', # Espaço
            'right_trigger': '0x08' # Backspace (exemplo, você pode mudar)
        }

        # Inicializa Pygame para o controle
        pygame.init()
        pygame.joystick.init()
        self.joystick = None

        # Variáveis StringVar para atualização da GUI
        self.status_var = tk.StringVar(value="Iniciando...")
        self.control_status_var = tk.StringVar(value="Nenhum controle conectado")
        self.gopher_status_var = tk.StringVar(value="Inativo")
        # Ajustei para 6 casas decimais para mostrar a sensibilidade super baixa
        self.speed_var = tk.StringVar(value=f"Velocidade: Média ({self.current_speed:.6f})")
        self.disabled_var = tk.StringVar(value="Gopher: Habilitado")

        # ConfigParser para carregar/salvar configurações
        # NOTA: self.config é inicializado aqui, mas pode ser re-inicializado em load_config
        # para garantir um estado limpo ao recriar o arquivo.
        self.config = configparser.ConfigParser()
        self.load_config() # Carrega configurações ou cria o arquivo padrão

        # Cria a interface do usuário
        self.create_widgets()

        # Tenta conectar ao controle após a interface estar pronta
        self.connect_controller()
        self.status_var.set("Pronto")

    def create_widgets(self,):
        """Cria e organiza todos os widgets da interface gráfica."""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Aba de Configurações
        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="Configurações")
        self._create_config_tab(config_frame)

        # Aba de Status
        status_frame = ttk.Frame(notebook)
        notebook.add(status_frame, text="Status")
        self._create_status_tab(status_frame)

        # Barra de status na parte inferior da janela
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, pady=(2,0))

    def _create_config_tab(self, parent):
        """Cria os widgets para a aba de Configurações."""
        canvas = tk.Canvas(parent)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # --- Seção de Controles do Mouse ---
        mouse_frame = ttk.LabelFrame(scrollable_frame, text="Controles do Mouse", padding="10")
        mouse_frame.pack(fill=tk.X, pady=5)

        ttk.Label(mouse_frame, text="Botão Esquerdo (Hex):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.mouse_left_entry = ttk.Entry(mouse_frame, width=15)
        self.mouse_left_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        # Usar self.config.get diretamente, pois load_config já garantiu que existe
        self.mouse_left_entry.insert(0, self.config.get('DEFAULT', 'mouse_left'))

        ttk.Label(mouse_frame, text="Botão Direito (Hex):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.mouse_right_entry = ttk.Entry(mouse_frame, width=15)
        self.mouse_right_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        self.mouse_right_entry.insert(0, self.config.get('DEFAULT', 'mouse_right'))

        ttk.Label(mouse_frame, text="Botão do Meio (Hex):").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.mouse_middle_entry = ttk.Entry(mouse_frame, width=15)
        self.mouse_middle_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        self.mouse_middle_entry.insert(0, self.config.get('DEFAULT', 'mouse_middle'))

        # --- Seção de Configurações do Gopher ---
        gopher_config_frame = ttk.LabelFrame(scrollable_frame, text="Configurações do Gopher", padding="10")
        gopher_config_frame.pack(fill=tk.X, pady=5)

        ttk.Label(gopher_config_frame, text="Ocultar Janela (Hex):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.hide_window_entry = ttk.Entry(gopher_config_frame, width=15)
        self.hide_window_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        self.hide_window_entry.insert(0, self.config.get('DEFAULT', 'hide_window'))

        ttk.Label(gopher_config_frame, text="Desabilitar Gopher (Hex):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.disable_gopher_entry = ttk.Entry(gopher_config_frame, width=15)
        self.disable_gopher_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        self.disable_gopher_entry.insert(0, self.config.get('DEFAULT', 'disable_gopher'))

        ttk.Label(gopher_config_frame, text="Mudar Velocidade (Hex):").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.speed_change_entry = ttk.Entry(gopher_config_frame, width=15)
        self.speed_change_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        self.speed_change_entry.insert(0, self.config.get('DEFAULT', 'speed_change'))

        # Botões de ajuste de sensibilidade
        sensitivity_frame = ttk.Frame(gopher_config_frame)
        sensitivity_frame.grid(row=3, column=0, columnspan=2, pady=5)
        ttk.Button(sensitivity_frame, text="Diminuir Sensibilidade", command=lambda: self.adjust_sensitivity(-0.01)).pack(side=tk.LEFT, padx=5)
        ttk.Button(sensitivity_frame, text="Aumentar Sensibilidade", command=lambda: self.adjust_sensitivity(0.01)).pack(side=tk.LEFT, padx=5)


        # --- Seção de Mapeamento de Teclas ---
        keyboard_frame = ttk.LabelFrame(scrollable_frame, text="Mapeamento de Teclas (Hex)", padding="10")
        keyboard_frame.pack(fill=tk.X, pady=5)

        # Mapeamentos de teclas do controle para teclas do teclado (usando códigos virtuais do Windows)
        mappings = [
            ('DPad Up', 'dpad_up'), ('DPad Down', 'dpad_down'),
            ('DPad Left', 'dpad_left'), ('DPad Right', 'dpad_right'),
            ('Start', 'start'), ('Back', 'back'),
            ('Left Thumb', 'left_thumb'), ('Right Thumb', 'right_thumb'),
            ('Left Shoulder', 'left_shoulder'), ('Right Shoulder', 'right_shoulder'),
            ('A Button', 'a_button'), ('B Button', 'b_button'),
            ('X Button', 'x_button'), ('Y Button', 'y_button'),
            ('Left Trigger', 'left_trigger'), ('Right Trigger', 'right_trigger')
        ]

        self.entry_widgets = {}
        for i, (label, key) in enumerate(mappings):
            ttk.Label(keyboard_frame, text=f"{label}:").grid(row=i, column=0, sticky=tk.W, padx=5, pady=2)
            entry = ttk.Entry(keyboard_frame, width=15)
            entry.grid(row=i, column=1, sticky=tk.W, padx=5, pady=2)
            entry.insert(0, self.config.get('DEFAULT', key))
            self.entry_widgets[key] = entry # Armazena o widget para acesso posterior

        # --- Botões de Ação ---
        button_frame = ttk.Frame(scrollable_frame)
        button_frame.pack(fill=tk.X, pady=10)

        ttk.Button(button_frame, text="Salvar Configurações", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Carregar Padrões", command=self.load_defaults).pack(side=tk.LEFT, padx=5)


    def _create_status_tab(self, parent):
        """Cria os widgets para a aba de Status."""
        # Status do Controle
        control_frame = ttk.LabelFrame(parent, text="Status do Controle", padding="10")
        control_frame.pack(fill=tk.X, pady=5)
        ttk.Label(control_frame, textvariable=self.control_status_var).pack(pady=2)
        ttk.Button(control_frame, text="Reconectar Controle", command=self.connect_controller).pack(pady=5)

        # Status do Gopher
        gopher_frame = ttk.LabelFrame(parent, text="Status do Gopher", padding="10")
        gopher_frame.pack(fill=tk.X, pady=5)
        ttk.Label(gopher_frame, textvariable=self.gopher_status_var).pack(pady=2)

        button_frame = ttk.Frame(gopher_frame)
        button_frame.pack(pady=10)
        self.start_button = ttk.Button(button_frame, text="Iniciar Gopher", command=self.start_gopher)
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = ttk.Button(button_frame, text="Parar Gopher", command=self.stop_gopher, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        # Configurações Atuais
        settings_frame = ttk.LabelFrame(parent, text="Configurações Atuais", padding="10")
        settings_frame.pack(fill=tk.X, pady=5)
        ttk.Label(settings_frame, textvariable=self.speed_var).pack(anchor=tk.W, pady=2)
        ttk.Label(settings_frame, textvariable=self.disabled_var).pack(anchor=tk.W, pady=2)

    def connect_controller(self):
        """Tenta inicializar ou reconectar o joystick."""
        try:
            pygame.joystick.quit() # Garante que não há joysticks antigos inicializados
            pygame.joystick.init() # Re-inicializa o módulo

            if pygame.joystick.get_count() > 0:
                self.joystick = pygame.joystick.Joystick(0)
                self.joystick.init()
                self.control_status_var.set(f"Controle conectado: {self.joystick.get_name()}")
                self.status_var.set("Controle conectado com sucesso!")
            else:
                self.joystick = None
                self.control_status_var.set("Nenhum controle conectado")
                self.status_var.set("Nenhum controle encontrado.")
        except pygame.error as e:
            self.joystick = None
            self.control_status_var.set(f"Erro Pygame: {e}")
            self.status_var.set(f"Erro ao conectar controle: {e}")
        except Exception as e:
            self.joystick = None
            self.control_status_var.set(f"Erro: {e}")
            self.status_var.set(f"Erro inesperado ao conectar controle: {e}")

    def load_config(self):
        """Carrega as configurações do arquivo .ini ou cria um novo com padrões."""
        # Inicializa configparser. Isso limpa qualquer estado anterior se for chamado novamente.
        self.config = configparser.ConfigParser()

        # Tenta ler o arquivo
        read_success_files = self.config.read(CONFIG_FILE)

        needs_recreation = False

        if not read_success_files:
            # Arquivo não existia ou não pôde ser lido (ex: permissão, formato inválido)
            needs_recreation = True
        elif not self.config.has_section('DEFAULT'):
            # Se o arquivo foi lido mas não tem a seção DEFAULT (o que indica um arquivo mal formado para nós)
            needs_recreation = True


        if needs_recreation:
            messagebox.showwarning("Configuração",
                                 f"O arquivo de configuração '{CONFIG_FILE}' está ausente ou corrompido. "
                                 "Um novo arquivo padrão será criado.")
            self.status_var.set("Recriando configurações padrão.")

            # Popula com os valores padrão.
            # A seção 'DEFAULT' será criada implicitamente pelo configparser.
            for key, value in self.default_mappings.items():
                self.config['DEFAULT'][key] = value
            self.config['DEFAULT']['sensitivity_multiplier'] = str(1.0) # Salva a sensibilidade padrão

            self.sensitivity_multiplier = 1.0 # Reseta para padrão
            self.current_speed = self.base_speed * self.sensitivity_multiplier
            self.update_speed_display()

            # Tenta salvar o novo arquivo de configuração padrão
            try:
                with open(CONFIG_FILE, 'w') as configfile:
                    self.config.write(configfile)
                self.status_var.set("Arquivo de configuração padrão criado e carregado.")
            except Exception as write_e:
                messagebox.showerror("Erro de Escrita", f"Não foi possível salvar o novo arquivo de configuração padrão. Verifique as permissões. Erro: {write_e}")
                self.status_var.set("Falha ao criar arquivo de configuração padrão.")
        else:
            # O arquivo foi lido e a seção DEFAULT existe.
            # Garante que todos os mapeamentos padrão existam (para compatibilidade futura)
            for key, value in self.default_mappings.items():
                if not self.config.has_option('DEFAULT', key):
                    self.config['DEFAULT'][key] = value # Adiciona se estiver faltando

            # Carrega a sensibilidade salva
            self.sensitivity_multiplier = self.config.getfloat('DEFAULT', 'sensitivity_multiplier', fallback=1.0)
            self.current_speed = self.base_speed * self.sensitivity_multiplier
            self.update_speed_display()

            # Salva o arquivo novamente para garantir que quaisquer novas chaves padrão foram adicionadas
            try:
                with open(CONFIG_FILE, 'w') as configfile:
                    self.config.write(configfile)
                self.status_var.set("Configurações carregadas e atualizadas com sucesso.")
            except Exception as write_e:
                messagebox.showwarning("Aviso", f"Não foi possível salvar a atualização das configurações. Erro: {write_e}")
                self.status_var.set("Configurações carregadas, mas falha ao salvar atualizações.")


    def save_config(self):
        """Salva as configurações atuais no arquivo .ini."""
        try:
            # Atualiza os valores do config com os da interface
            self.config['DEFAULT']['mouse_left'] = self.mouse_left_entry.get()
            self.config['DEFAULT']['mouse_right'] = self.mouse_right_entry.get()
            self.config['DEFAULT']['mouse_middle'] = self.mouse_middle_entry.get()
            self.config['DEFAULT']['hide_window'] = self.hide_window_entry.get()
            self.config['DEFAULT']['disable_gopher'] = self.disable_gopher_entry.get()
            self.config['DEFAULT']['speed_change'] = self.speed_change_entry.get()

            # Salva todos os mapeamentos de teclas dinamicamente
            for key, entry in self.entry_widgets.items():
                self.config['DEFAULT'][key] = entry.get()

            # Salva a sensibilidade atual
            self.config['DEFAULT']['sensitivity_multiplier'] = str(self.sensitivity_multiplier)

            # Escreve no arquivo
            with open(CONFIG_FILE, 'w') as configfile:
                self.config.write(configfile)

            self.status_var.set("Configurações salvas com sucesso!")
            messagebox.showinfo("Sucesso", "Configurações salvas com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao salvar configurações: {str(e)}")
            self.status_var.set("Erro ao salvar configurações.")

    def load_defaults(self):
        """Carrega os mapeamentos padrão na interface gráfica e salva."""
        response = messagebox.askyesno("Confirmar Padrões", "Tem certeza que deseja carregar as configurações padrão? Isso sobrescreverá suas configurações atuais.")
        if not response:
            return

        try:
            # Re-inicializa o config parser para garantir um estado limpo para os padrões
            self.config = configparser.ConfigParser()

            # Popula a interface e o objeto config com os valores padrão
            self.mouse_left_entry.delete(0, tk.END)
            self.mouse_left_entry.insert(0, self.default_mappings['mouse_left'])
            self.config['DEFAULT']['mouse_left'] = self.default_mappings['mouse_left']

            self.mouse_right_entry.delete(0, tk.END)
            self.mouse_right_entry.insert(0, self.default_mappings['mouse_right'])
            self.config['DEFAULT']['mouse_right'] = self.default_mappings['mouse_right']

            self.mouse_middle_entry.delete(0, tk.END)
            self.mouse_middle_entry.insert(0, self.default_mappings['mouse_middle'])
            self.config['DEFAULT']['mouse_middle'] = self.default_mappings['mouse_middle']

            self.hide_window_entry.delete(0, tk.END)
            self.hide_window_entry.insert(0, self.default_mappings['hide_window'])
            self.config['DEFAULT']['hide_window'] = self.default_mappings['hide_window']

            self.disable_gopher_entry.delete(0, tk.END)
            self.disable_gopher_entry.insert(0, self.default_mappings['disable_gopher'])
            self.config['DEFAULT']['disable_gopher'] = self.default_mappings['disable_gopher']

            self.speed_change_entry.delete(0, tk.END)
            self.speed_change_entry.insert(0, self.default_mappings['speed_change'])
            self.config['DEFAULT']['speed_change'] = self.default_mappings['speed_change']

            for key, entry in self.entry_widgets.items():
                entry.delete(0, tk.END)
                entry.insert(0, self.default_mappings[key])
                self.config['DEFAULT'][key] = self.default_mappings[key]


            self.sensitivity_multiplier = 1.0 # Reseta sensibilidade para o padrão
            self.current_speed = self.base_speed * self.sensitivity_multiplier
            self.update_speed_display()
            self.config['DEFAULT']['sensitivity_multiplier'] = str(self.sensitivity_multiplier)

            self.status_var.set("Padrões carregados na interface.")
            # Salva automaticamente os padrões
            self.save_config()
            messagebox.showinfo("Sucesso", "Configurações padrão carregadas e salvas com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao carregar padrões: {str(e)}")
            self.status_var.set("Erro ao carregar padrões.")

    def adjust_sensitivity(self, delta):
        """Ajusta a sensibilidade do mouse."""
        # Limita a sensibilidade para evitar valores extremos (e negativos)
        self.sensitivity_multiplier = max(0.001, min(10.0, self.sensitivity_multiplier + delta)) # Limites ajustados para ser bem flexível
        self.current_speed = self.base_speed * self.sensitivity_multiplier
        self.update_speed_display()
        self.status_var.set(f"Sensibilidade ajustada para {self.sensitivity_multiplier:.2f}x") # Mostrar 2 casas decimais
        self.save_config() # Salva a sensibilidade ajustada

    def update_speed_display(self):
        """Atualiza o texto da velocidade na interface."""
        # Os nomes "Baixa", "Média", "Alta" são mais representativos agora
        if self.sensitivity_multiplier < self.SPEED_MED_MULTIPLIER * 0.8: # Ajustei os limites para as categorias
            speed_name = "Baixa"
        elif self.sensitivity_multiplier > self.SPEED_MED_MULTIPLIER * 1.2:
            speed_name = "Alta"
        else:
            speed_name = "Média"
        self.speed_var.set(f"Velocidade: {speed_name} ({self.current_speed:.6f}) - Multiplicador: {self.sensitivity_multiplier:.2f}x")


    def start_gopher(self):
        """Inicia o thread do controle para emulação."""
        if not self.joystick:
            messagebox.showerror("Erro", "Nenhum controle conectado! Conecte um controle antes de iniciar.")
            return

        if not self.running:
            self.running = True
            self.controller_thread = threading.Thread(target=self._controller_loop, daemon=True)
            self.controller_thread.start()

            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.gopher_status_var.set("Ativo - Controle em funcionamento")
            self.status_var.set("Gopher iniciado com sucesso.")

    def stop_gopher(self):
        """Para o thread do controle."""
        if self.running:
            self.running = False
            if self.controller_thread and self.controller_thread.is_alive():
                self.controller_thread.join(timeout=1) # Espera o thread terminar

            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.gopher_status_var.set("Inativo")
            self.status_var.set("Gopher parado.")

    def _controller_loop(self):
        """Loop principal que lê o controle e simula mouse/teclado."""
        button_states = {} # Armazena o estado anterior dos botões
        trigger_states = {'left': False, 'right': False} # Armazena o estado anterior dos gatilhos
        x_rest, y_rest = 0.0, 0.0 # Acumuladores para sub-pixel de movimento

        while self.running:
            start_time = time.time()
            pygame.event.pump() # Processa eventos internos do Pygame

            if not self.disabled and self.joystick:
                # --- Movimento do Mouse (Analógico Esquerdo) ---
                x, y = self._get_mouse_position() # Posição atual do mouse
                axis_x = self.joystick.get_axis(0) * 32767 # Eixo X do analógico esquerdo (horizontal)
                axis_y = self.joystick.get_axis(1) * 32767 # Eixo Y do analógico esquerdo (vertical)

                dx, dy = 0, 0

                # Verifica se o movimento está fora da DEAD_ZONE
                if (axis_x**2 + axis_y**2) > DEAD_ZONE**2:
                    length = (axis_x**2 + axis_y**2)**0.5
                    # Calcula o multiplicador de movimento
                    # A velocidade é aplicada aqui, escalando com a distância do centro
                    mult = self.current_speed * (length - DEAD_ZONE) / length * 1000

                    dx = axis_x * mult
                    dy = axis_y * mult # Eixo Y está correto agora (para cima/para baixo)

                new_x = x + dx + x_rest
                new_y = y + dy + y_rest

                x_rest = new_x - int(new_x) # Acumula a parte fracionária
                y_rest = new_y - int(new_y)

                self._set_mouse_position(int(new_x), int(new_y))

                # --- Rolagem do Mouse (Analógico Direito) ---
                scroll_axis_y = self.joystick.get_axis(3) * 32767 # Eixo Y do analógico direito
                if abs(scroll_axis_y) > SCROLL_DEAD_ZONE:
                    scroll_amount = int(scroll_axis_y * 0.005) # Ajuste este valor se a rolagem for muito rápida
                    pyautogui.scroll(scroll_amount)

                # --- Leitura e Mapeamento dos Botões ---
                num_buttons = self.joystick.get_numbuttons()
                for button_idx in range(num_buttons):
                    current_state = self.joystick.get_button(button_idx)
                    prev_state = button_states.get(button_idx, False)

                    if current_state and not prev_state:
                        # Botão foi pressionado
                        self._handle_button_press(button_idx)
                    elif not current_state and prev_state:
                        # Botão foi liberado
                        self._handle_button_release(button_idx)

                    button_states[button_idx] = current_state

                # --- Leitura e Mapeamento dos Gatilhos ---
                # Gatilhos retornam valores de -1 (não pressionado) a 1 (totalmente pressionado)
                # Convertemos para 0 a 1 para facilitar a lógica (0=não, 1=pressionado)
                left_trigger_val = (self.joystick.get_axis(4) + 1) / 2
                right_trigger_val = (self.joystick.get_axis(5) + 1) / 2

                # Limiar para considerar o gatilho "pressionado"
                trigger_threshold = 0.5

                if left_trigger_val > trigger_threshold and not trigger_states['left']:
                    trigger_states['left'] = True
                    self._handle_trigger('left', True)
                elif left_trigger_val <= trigger_threshold and trigger_states['left']:
                    trigger_states['left'] = False
                    self._handle_trigger('left', False)

                if right_trigger_val > trigger_threshold and not trigger_states['right']:
                    trigger_states['right'] = True
                    self._handle_trigger('right', True)
                elif right_trigger_val <= trigger_threshold and trigger_states['right']:
                    trigger_states['right'] = False
                    self._handle_trigger('right', False)

            # Controla a taxa de atualização do loop
            elapsed = time.time() - start_time
            if elapsed < SLEEP_AMOUNT:
                time.sleep(SLEEP_AMOUNT - elapsed)

    def _get_mouse_position(self):
        """Retorna a posição atual do cursor do mouse."""
        pt = POINT()
        windll.user32.GetCursorPos(byref(pt))
        return pt.x, pt.y

    def _set_mouse_position(self, x, y):
        """Define a posição do cursor do mouse."""
        windll.user32.SetCursorPos(x, y)

    def _handle_button_press(self, button_idx):
        """Lida com o evento de botão pressionado."""
        button_hex = hex(button_idx)

        # Mapeamento para cliques do mouse
        if button_hex == self.mouse_left_entry.get():
            pyautogui.mouseDown(button='left')
        elif button_hex == self.mouse_right_entry.get():
            pyautogui.mouseDown(button='right')
        elif button_hex == self.mouse_middle_entry.get():
            pyautogui.mouseDown(button='middle')
        # Mapeamento para funções do Gopher
        elif button_hex == self.hide_window_entry.get():
            self._toggle_window_visibility()
        elif button_hex == self.disable_gopher_entry.get():
            self.disabled = not self.disabled
            self.disabled_var.set(f"Gopher: {'Desabilitado' if self.disabled else 'Habilitado'}")
            self.status_var.set(f"Gopher {'desabilitado' if self.disabled else 'habilitado'}.")
        elif button_hex == self.speed_change_entry.get():
            if self.sensitivity_multiplier <= self.SPEED_LOW_MULTIPLIER:
                self.sensitivity_multiplier = self.SPEED_MED_MULTIPLIER
            elif self.sensitivity_multiplier <= self.SPEED_MED_MULTIPLIER:
                self.sensitivity_multiplier = self.SPEED_HIGH_MULTIPLIER
            else:
                self.sensitivity_multiplier = self.SPEED_LOW_MULTIPLIER
            self.current_speed = self.base_speed * self.sensitivity_multiplier
            self.update_speed_display()
            self.save_config() # Salva a nova velocidade

        # Mapeamento para teclas do teclado
        for key, entry_widget in self.entry_widgets.items():
            if button_hex == entry_widget.get() and entry_widget.get() != '0x0': # '0x0' como valor nulo
                pyautogui.keyDown(self._get_key_from_hex(entry_widget.get()))

    def _handle_button_release(self, button_idx):
        """Lida com o evento de botão liberado."""
        button_hex = hex(button_idx)

        # Mapeamento para cliques do mouse
        if button_hex == self.mouse_left_entry.get():
            pyautogui.mouseUp(button='left')
        elif button_hex == self.mouse_right_entry.get():
            pyautogui.mouseUp(button='right')
        elif button_hex == self.mouse_middle_entry.get():
            pyautogui.mouseUp(button='middle')

        # Mapeamento para teclas do teclado
        for key, entry_widget in self.entry_widgets.items():
            if button_hex == entry_widget.get() and entry_widget.get() != '0x0':
                pyautogui.keyUp(self._get_key_from_hex(entry_widget.get()))

    def _handle_trigger(self, trigger_side, pressed):
        """Lida com o evento de gatilho (esquerdo/direito) pressionado/liberado."""
        if trigger_side == 'left':
            key_hex = self.entry_widgets['left_trigger'].get()
        else: # 'right'
            key_hex = self.entry_widgets['right_trigger'].get()

        if key_hex != '0x0':
            key_to_press = self._get_key_from_hex(key_hex)
            if key_to_press is not None: # Verifica se a tecla é válida
                if pressed:
                    pyautogui.keyDown(key_to_press)
                else:
                    pyautogui.keyUp(key_to_press)

    def _get_key_from_hex(self, hex_str):
        """Converte um valor hexadecimal de código de tecla virtual do Windows para o nome da tecla do pyautogui."""
        if not hex_str or hex_str.lower() == '0x0':
            return None # Retorna None ou algum valor que indique "nenhuma tecla" para pyautogui

        try:
            # Remove o prefixo '0x' se existir e converte para inteiro
            key_code = int(hex_str, 16)

            # Mapeamento de códigos de tecla virtuais para nomes de teclas do pyautogui
            # Este mapa não precisa incluir 'leftclick', 'rightclick' etc. pois eles são tratados pelos botões do mouse.
            key_map = {
                0x08: 'backspace', 0x09: 'tab',
                0x0C: 'clear', 0x0D: 'enter',
                0x10: 'shift', 0x11: 'ctrl', 0x12: 'alt',
                0x13: 'pause', 0x14: 'capslock', 0x1B: 'esc',
                0x20: 'space',
                0x21: 'pgup', 0x22: 'pgdn',
                0x23: 'end', 0x24: 'home',
                0x25: 'left', 0x26: 'up', 0x27: 'right', 0x28: 'down',
                0x2D: 'insert', 0x2E: 'delete',
                0x30: '0', 0x31: '1', 0x32: '2', 0x33: '3', 0x34: '4',
                0x35: '5', 0x36: '6', 0x37: '7', 0x38: '8', 0x39: '9',
                0x41: 'a', 0x42: 'b', 0x43: 'c', 0x44: 'd', 0x45: 'e',
                0x46: 'f', 0x47: 'g', 0x48: 'h', 0x49: 'i', 0x4A: 'j',
                0x4B: 'k', 0x4C: 'l', 0x4D: 'm', 0x4E: 'n', 0x4F: 'o',
                0x50: 'p', 0x51: 'q', 0x52: 'r', 0x53: 's', 0x54: 't',
                0x55: 'u', 0x56: 'v', 0x57: 'w', 0x58: 'x', 0x59: 'y', 0x5A: 'z',
                0x5B: 'winleft', 0x5C: 'winright',
                0x60: 'num0', 0x61: 'num1', 0x62: 'num2', 0x63: 'num3',
                0x64: 'num4', 0x65: 'num5', 0x66: 'num6', 0x67: 'num7',
                0x68: 'num8', 0x69: 'num9',
                0x6A: 'multiply', 0x6B: 'add', 0x6C: 'separator', 0x6D: 'subtract',
                0x6E: 'decimal', 0x6F: 'divide',
                0x70: 'f1', 0x71: 'f2', 0x72: 'f3', 0x73: 'f4', 0x74: 'f5',
                0x75: 'f6', 0x76: 'f7', 0x77: 'f8', 0x78: 'f9', 0x79: 'f10',
                0x7A: 'f11', 0x7B: 'f12',
                0x90: 'numlock', 0x91: 'scrolllock',
                0xA0: 'shiftleft', 0xA1: 'shiftright',
                0xA2: 'ctrlleft', 0xA3: 'ctrlright',
                0xA4: 'altleft', 0xA5: 'altright',
                0xA6: 'browser_back', 0xA7: 'browser_forward', 0xA8: 'browser_refresh',
                0xA9: 'browser_stop', 0xAA: 'browser_search', 0xAB: 'browser_favorites',
                0xAC: 'browser_home', 0xAD: 'volumemute', 0xAE: 'volumedown',
                0xAF: 'volumeup', 0xB0: 'nexttrack', 0xB1: 'prevtrack',
                0xB2: 'stop', 0xB3: 'playpause', 0xB4: 'launchmail',
                0xB5: 'launchmediaselect', 0xB6: 'launchapp1', 0xB7: 'launchapp2',
                0xBA: ';', 0xBB: '=', 0xBC: ',', 0xBD: '-', 0xBE: '.', 0xBF: '/',
                0xC0: '`', 0xDB: '[', 0xDC: '\\', 0xDD: ']', 0xDE: "'"
            }
            return key_map.get(key_code, None) # Retorna None se não encontrar o mapeamento
        except ValueError:
            self.status_var.set(f"Erro: Valor Hex Inválido: '{hex_str}'")
            return None # Retorna None para valores hex inválidos

    def _toggle_window_visibility(self):
        """Alterna a visibilidade da janela do console."""
        console_window = windll.kernel32.GetConsoleWindow()
        if console_window:
            if self.hidden:
                windll.user32.ShowWindow(console_window, 1)  # SW_SHOWNORMAL (mostrar)
                self.hidden = False
                self.status_var.set("Janela mostrada.")
            else:
                windll.user32.ShowWindow(console_window, 0)  # SW_HIDE (ocultar)
                self.hidden = True
                self.status_var.set("Janela ocultada.")

    def on_closing(self):
        """Lida com o fechamento da janela da aplicação."""
        self.stop_gopher() # Garante que o thread do controle pare
        pygame.joystick.quit() # Desinicializa o joystick
        pygame.quit() # Desinicializa o Pygame
        self.root.destroy() # Fecha a janela do Tkinter

# --- Função Principal para Iniciar a Aplicação ---
def main():
    root = tk.Tk()
    app = Gopher360App(root)
    root.mainloop()

if __name__ == "__main__":
    main()