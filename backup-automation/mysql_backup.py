#!/usr/bin/env python3
"""
MySQL Backup Automation Script
Automatiza backup de bancos MySQL para AWS S3 com rotação e notificações
Author: Gabriel Monteiro
"""

import os
import sys
import boto3
import logging
import subprocess
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
import configparser

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/mysql_backup.log'),
        logging.StreamHandler()
    ]
)

class MySQLBackupManager:
    def __init__(self, config_file='backup_config.ini'):
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        
        # MySQL Config
        self.mysql_host = self.config.get('mysql', 'host', fallback='localhost')
        self.mysql_user = self.config.get('mysql', 'user')
        self.mysql_password = self.config.get('mysql', 'password')
        self.databases = self.config.get('mysql', 'databases').split(',')
        
        # AWS Config
        self.s3_bucket = self.config.get('aws', 's3_bucket')
        self.aws_region = self.config.get('aws', 'region', fallback='us-east-1')
        
        # Backup Config
        self.backup_dir = self.config.get('backup', 'local_dir', fallback='/tmp/mysql_backups')
        self.retention_days = int(self.config.get('backup', 'retention_days', fallback='30'))
        
        # Email Config
        self.smtp_server = self.config.get('email', 'smtp_server', fallback='smtp.gmail.com')
        self.smtp_port = int(self.config.get('email', 'smtp_port', fallback='587'))
        self.email_user = self.config.get('email', 'user')
        self.email_password = self.config.get('email', 'password')
        self.notification_email = self.config.get('email', 'notification_email')
        
        # Inicializar S3 client
        self.s3_client = boto3.client('s3', region_name=self.aws_region)
        
        # Criar diretório local se não existir
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)

    def create_mysql_dump(self, database):
        """Cria dump do banco MySQL"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dump_file = f"{self.backup_dir}/{database}_{timestamp}.sql"
        
        cmd = [
            'mysqldump',
            f'--host={self.mysql_host}',
            f'--user={self.mysql_user}',
            f'--password={self.mysql_password}',
            '--single-transaction',
            '--routines',
            '--triggers',
            database
        ]
        
        try:
            logging.info(f"Criando backup do banco {database}...")
            with open(dump_file, 'w') as f:
                result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)
                
            if result.returncode != 0:
                raise Exception(f"Erro no mysqldump: {result.stderr}")
                
            # Comprimir o arquivo
            compressed_file = f"{dump_file}.gz"
            subprocess.run(['gzip', dump_file], check=True)
            
            logging.info(f"Backup criado: {compressed_file}")
            return compressed_file
            
        except Exception as e:
            logging.error(f"Erro ao criar backup de {database}: {str(e)}")
            raise

    def upload_to_s3(self, local_file, database):
        """Upload do backup para S3"""
        try:
            file_name = os.path.basename(local_file)
            s3_key = f"mysql_backups/{database}/{file_name}"
            
            logging.info(f"Uploading {file_name} para S3...")
            self.s3_client.upload_file(local_file, self.s3_bucket, s3_key)
            
            # Adicionar tags para organização
            self.s3_client.put_object_tagging(
                Bucket=self.s3_bucket,
                Key=s3_key,
                Tagging={
                    'TagSet': [
                        {'Key': 'Type', 'Value': 'mysql_backup'},
                        {'Key': 'Database', 'Value': database},
                        {'Key': 'Date', 'Value': datetime.now().strftime('%Y-%m-%d')}
                    ]
                }
            )
            
            logging.info(f"Upload concluído: s3://{self.s3_bucket}/{s3_key}")
            return s3_key
            
        except Exception as e:
            logging.error(f"Erro no upload para S3: {str(e)}")
            raise

    def cleanup_old_backups(self, database):
        """Remove backups antigos do S3 baseado na retenção configurada"""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            prefix = f"mysql_backups/{database}/"
            
            response = self.s3_client.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix=prefix
            )
            
            if 'Contents' not in response:
                return
                
            deleted_count = 0
            for obj in response['Contents']:
                if obj['LastModified'].replace(tzinfo=None) < cutoff_date:
                    self.s3_client.delete_object(
                        Bucket=self.s3_bucket,
                        Key=obj['Key']
                    )
                    logging.info(f"Backup antigo removido: {obj['Key']}")
                    deleted_count += 1
                    
            if deleted_count > 0:
                logging.info(f"Limpeza concluída: {deleted_count} backups antigos removidos")
                
        except Exception as e:
            logging.error(f"Erro na limpeza de backups antigos: {str(e)}")

    def send_notification(self, subject, message, is_error=False):
        """Envia notificação por email"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_user
            msg['To'] = self.notification_email
            msg['Subject'] = f"[MySQL Backup] {subject}"
            
            if is_error:
                message = f"❌ ERRO no backup:\n\n{message}"
            else:
                message = f"✅ Backup concluído com sucesso:\n\n{message}"
                
            msg.attach(MIMEText(message, 'plain'))
            
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.email_user, self.email_password)
            server.send_message(msg)
            server.quit()
            
            logging.info("Notificação enviada por email")
            
        except Exception as e:
            logging.error(f"Erro ao enviar notificação: {str(e)}")

    def run_backup(self):
        """Executa o processo completo de backup"""
        start_time = datetime.now()
        success_count = 0
        error_count = 0
        backup_details = []
        
        logging.info("=== Iniciando processo de backup MySQL ===")
        
        for database in self.databases:
            database = database.strip()
            try:
                # Criar dump
                dump_file = self.create_mysql_dump(database)
                
                # Upload para S3
                s3_key = self.upload_to_s3(dump_file, database)
                
                # Limpeza de backups antigos
                self.cleanup_old_backups(database)
                
                # Remover arquivo local
                os.remove(dump_file)
                
                success_count += 1
                backup_details.append(f"✅ {database}: {os.path.basename(dump_file)}")
                
            except Exception as e:
                error_count += 1
                backup_details.append(f"❌ {database}: {str(e)}")
                logging.error(f"Falha no backup de {database}: {str(e)}")
        
        # Relatório final
        end_time = datetime.now()
        duration = end_time - start_time
        
        report = f"""
Relatório de Backup MySQL
========================
Data/Hora: {start_time.strftime('%d/%m/%Y %H:%M:%S')}
Duração: {duration}
Bancos processados: {len(self.databases)}
Sucessos: {success_count}
Erros: {error_count}

Detalhes:
{chr(10).join(backup_details)}

Configurações:
- Bucket S3: {self.s3_bucket}
- Retenção: {self.retention_days} dias
- Diretório local: {self.backup_dir}
        """
        
        logging.info(report)
        
        # Enviar notificação
        if error_count > 0:
            self.send_notification(f"Backup com {error_count} erro(s)", report, is_error=True)
        else:
            self.send_notification("Backup concluído", report)
        
        return success_count == len(self.databases)

def main():
    """Função principal"""
    try:
        backup_manager = MySQLBackupManager()
        success = backup_manager.run_backup()
        
        if success:
            logging.info("Todos os backups foram concluídos com sucesso!")
            sys.exit(0)
        else:
            logging.error("Alguns backups falharam. Verifique os logs.")
            sys.exit(1)
            
    except Exception as e:
        logging.error(f"Erro crítico no processo de backup: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
