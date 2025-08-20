#!/usr/bin/env python3
"""
System Health Check Script
Monitora recursos do sistema e gera relatórios automáticos
Author: Gabriel Monteiro
"""

import psutil
import platform
import subprocess
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import argparse
import logging

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/system_health.log'),
        logging.StreamHandler()
    ]
)

class SystemHealthChecker:
    def __init__(self):
        self.alerts = []
        self.warnings = []
        self.info = []
        
    def check_cpu_usage(self, threshold=80):
        """Verifica uso de CPU"""
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        
        status = {
            'metric': 'CPU Usage',
            'value': f"{cpu_percent}%",
            'cores': cpu_count,
            'frequency': f"{cpu_freq.current:.0f}MHz" if cpu_freq else "N/A",
            'status': 'OK'
        }
        
        if cpu_percent > threshold:
            status['status'] = 'CRITICAL'
            self.alerts.append(f"🔴 CPU usage crítico: {cpu_percent}% (threshold: {threshold}%)")
        elif cpu_percent > threshold * 0.8:
            status['status'] = 'WARNING'
            self.warnings.append(f"🟡 CPU usage alto: {cpu_percent}%")
        else:
            self.info.append(f"✅ CPU usage normal: {cpu_percent}%")
            
        return status
    
    def check_memory_usage(self, threshold=85):
        """Verifica uso de memória"""
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        memory_percent = memory.percent
        memory_available = memory.available // (1024**3)  # GB
        memory_total = memory.total // (1024**3)  # GB
        
        status = {
            'metric': 'Memory Usage',
            'value': f"{memory_percent}%",
            'used': f"{memory_total - memory_available}GB",
            'total': f"{memory_total}GB",
            'available': f"{memory_available}GB",
            'swap_used': f"{swap.percent}%",
            'status': 'OK'
        }
        
        if memory_percent > threshold:
            status['status'] = 'CRITICAL'
            self.alerts.append(f"🔴 Memória crítica: {memory_percent}% (threshold: {threshold}%)")
        elif memory_percent > threshold * 0.8:
            status['status'] = 'WARNING'
            self.warnings.append(f"🟡 Memória alta: {memory_percent}%")
        else:
            self.info.append(f"✅ Memória normal: {memory_percent}%")
            
        return status
    
    def check_disk_usage(self, threshold=90):
        """Verifica uso de disco"""
        disk_status = []
        
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                percent = (usage.used / usage.total) * 100
                
                status = {
                    'mountpoint': partition.mountpoint,
                    'device': partition.device,
                    'fstype': partition.fstype,
                    'total': f"{usage.total // (1024**3)}GB",
                    'used': f"{usage.used // (1024**3)}GB",
                    'free': f"{usage.free // (1024**3)}GB",
                    'percent': f"{percent:.1f}%",
                    'status': 'OK'
                }
                
                if percent > threshold:
                    status['status'] = 'CRITICAL'
                    self.alerts.append(f"🔴 Disco crítico {partition.mountpoint}: {percent:.1f}%")
                elif percent > threshold * 0.8:
                    status['status'] = 'WARNING'
                    self.warnings.append(f"🟡 Disco alto {partition.mountpoint}: {percent:.1f}%")
                else:
                    self.info.append(f"✅ Disco normal {partition.mountpoint}: {percent:.1f}%")
                    
                disk_status.append(status)
                
            except PermissionError:
                continue
                
        return disk_status
    
    def check_services(self, services_list):
        """Verifica status de serviços"""
        service_status = []
        
        for service in services_list:
            try:
                result = subprocess.run(
                    ['systemctl', 'is-active', service],
                    capture_output=True,
                    text=True
                )
                
                is_active = result.stdout.strip() == 'active'
                
                status = {
                    'service': service,
                    'status': 'RUNNING' if is_active else 'STOPPED',
                    'active': is_active
                }
                
                if not is_active:
                    self.alerts.append(f"🔴 Serviço parado: {service}")
                else:
                    self.info.append(f"✅ Serviço rodando: {service}")
                    
                service_status.append(status)
                
            except Exception as e:
                logging.error(f"Erro ao verificar serviço {service}: {e}")
                
        return service_status
    
    def check_network_connectivity(self, hosts):
        """Verifica conectividade de rede"""
        network_status = []
        
        for host in hosts:
            try:
                result = subprocess.run(
                    ['ping', '-c', '3', '-W', '5', host],
                    capture_output=True,
                    text=True
                )
                
                is_reachable = result.returncode == 0
                
                # Extrair tempo de resposta
                if is_reachable:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if 'avg' in line:
                            avg_time = line.split('/')[-2]
                            break
                    else:
                        avg_time = "N/A"
                else:
                    avg_time = "N/A"
                
                status = {
                    'host': host,
                    'reachable': is_reachable,
                    'avg_response_time': f"{avg_time}ms" if avg_time != "N/A" else "N/A",
                    'status': 'OK' if is_reachable else 'FAILED'
                }
                
                if not is_reachable:
                    self.alerts.append(f"🔴 Host inacessível: {host}")
                else:
                    self.info.append(f"✅ Host acessível: {host} ({avg_time}ms)")
                    
                network_status.append(status)
                
            except Exception as e:
                logging.error(f"Erro ao verificar conectividade com {host}: {e}")
                
        return network_status
    
    def check_load_average(self):
        """Verifica load average do sistema"""
        try:
            load_avg = psutil.getloadavg()
            cpu_count = psutil.cpu_count()
            
            # Load average por core
            load_1m = load_avg[0] / cpu_count
            load_5m = load_avg[1] / cpu_count
            load_15m = load_avg[2] / cpu_count
            
            status = {
                'metric': 'Load Average',
                '1min': f"{load_avg[0]:.2f}",
                '5min': f"{load_avg[1]:.2f}",
                '15min': f"{load_avg[2]:.2f}",
                'per_core_1m': f"{load_1m:.2f}",
                'cpu_cores': cpu_count,
                'status': 'OK'
            }
            
            if load_1m > 1.5:
                status['status'] = 'CRITICAL'
                self.alerts.append(f"🔴 Load average crítico: {load_1m:.2f} por core")
            elif load_1m > 1.0:
                status['status'] = 'WARNING'
                self.warnings.append(f"🟡 Load average alto: {load_1m:.2f} por core")
            else:
                self.info.append(f"✅ Load average normal: {load_1m:.2f} por core")
                
            return status
            
        except Exception as e:
            logging.error(f"Erro ao verificar load average: {e}")
            return None
    
    def generate_report(self, cpu_status, memory_status, disk_status, 
                       service_status, network_status, load_status):
        """Gera relatório completo"""
        
        system_info = {
            'hostname': platform.node(),
            'os': f"{platform.system()} {platform.release()}",
            'architecture': platform.architecture()[0],
            'uptime': self.get_uptime(),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        report = {
            'system_info': system_info,
            'cpu': cpu_status,
            'memory': memory_status,
            'disk': disk_status,
            'services': service_status,
            'network': network_status,
            'load_average': load_status,
            'alerts': self.alerts,
            'warnings': self.warnings,
            'info': self.info,
            'summary': {
                'total_alerts': len(self.alerts),
                'total_warnings': len(self.warnings),
                'overall_status': 'CRITICAL' if self.alerts else ('WARNING' if self.warnings else 'OK')
            }
        }
        
        return report
    
    def get_uptime(self):
        """Obtém uptime do sistema"""
        try:
            uptime_seconds = psutil.boot_time()
            uptime_delta = datetime.now() - datetime.fromtimestamp(uptime_seconds)
            
            days = uptime_delta.days
            hours, remainder = divmod(uptime_delta.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            return f"{days}d {hours}h {minutes}m"
        except:
            return "N/A"
    
    def send_email_alert(self, report, email_config):
        """Envia alerta por email se houver problemas críticos"""
        if not self.alerts:
            return
            
        try:
            msg = MIMEMultipart()
            msg['From'] = email_config['from']
            msg['To'] = email_config['to']
            msg['Subject'] = f"🚨 ALERTA: Sistema {report['system_info']['hostname']}"
            
            body = f"""
ALERTA CRÍTICO - Sistema {report['system_info']['hostname']}
================================================

Data/Hora: {report['system_info']['timestamp']}
OS: {report['system_info']['os']}
Uptime: {report['system_info']['uptime']}

ALERTAS CRÍTICOS:
{chr(10).join(self.alerts)}

WARNINGS:
{chr(10).join(self.warnings) if self.warnings else 'Nenhum'}

RESUMO:
- CPU: {report['cpu']['value']}
- Memória: {report['memory']['value']}
- Load Average: {report['load_average']['per_core_1m']} por core

Verificar sistema imediatamente!
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port'])
            server.starttls()
            server.login(email_config['username'], email_config['password'])
            server.send_message(msg)
            server.quit()
            
            logging.info("Alerta enviado por email")
            
        except Exception as e:
            logging.error(f"Erro ao enviar email: {e}")

def main():
    parser = argparse.ArgumentParser(description='System Health Checker')
    parser.add_argument('--json', action='store_true', help='Output em formato JSON')
    parser.add_argument('--email', action='store_true', help='Enviar alertas por email')
    parser.add_argument('--services', nargs='+', default=['nginx', 'mysql', 'redis'], 
                       help='Serviços para verificar')
    parser.add_argument('--hosts', nargs='+', default=['8.8.8.8', 'google.com'],
                       help='Hosts para testar conectividade')
    
    args = parser.parse_args()
    
    checker = SystemHealthChecker()
    
    # Executar verificações
    cpu_status = checker.check_cpu_usage()
    memory_status = checker.check_memory_usage()
    disk_status = checker.check_disk_usage()
    service_status = checker.check_services(args.services)
    network_status = checker.check_network_connectivity(args.hosts)
    load_status = checker.check_load_average()
    
    # Gerar relatório
    report = checker.generate_report(
        cpu_status, memory_status, disk_status,
        service_status, network_status, load_status
    )
    
    # Output
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        # Relatório em texto
        print(f"\n{'='*60}")
        print(f"RELATÓRIO DE SAÚDE DO SISTEMA - {report['system_info']['hostname']}")
        print(f"{'='*60}")
        print(f"Data/Hora: {report['system_info']['timestamp']}")
        print(f"OS: {report['system_info']['os']}")
        print(f"Uptime: {report['system_info']['uptime']}")
        print(f"Status Geral: {report['summary']['overall_status']}")
        
        if checker.alerts:
            print(f"\n🚨 ALERTAS CRÍTICOS ({len(checker.alerts)}):")
            for alert in checker.alerts:
                print(f"  {alert}")
                
        if checker.warnings:
            print(f"\n⚠️  WARNINGS ({len(checker.warnings)}):")
            for warning in checker.warnings:
                print(f"  {warning}")
                
        print(f"\n✅ INFORMAÇÕES ({len(checker.info)}):")
        for info in checker.info[:5]:  # Mostrar apenas as primeiras 5
            print(f"  {info}")
    
    # Enviar email se solicitado e houver alertas
    if args.email and checker.alerts:
        email_config = {
            'from': 'alerts@company.com',
            'to': 'admin@company.com',
            'smtp_server': 'smtp.gmail.com',
            'smtp_port': 587,
            'username': 'alerts@company.com',
            'password': 'app_password'
        }
        checker.send_email_alert(report, email_config)
    
    # Exit code baseado no status
    if checker.alerts:
        exit(2)  # Critical
    elif checker.warnings:
        exit(1)  # Warning
    else:
        exit(0)  # OK

if __name__ == "__main__":
    main()
