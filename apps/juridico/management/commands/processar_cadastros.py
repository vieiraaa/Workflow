import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.juridico import processamento


class Command(BaseCommand):
    help = (
        "Worker do cadastro de processos (CAD-07): processa a fila de PDFs/números, um por vez. "
        "Sem opções roda em laço; --uma-vez processa a fila atual e sai. Ctrl+C encerra."
    )

    def add_arguments(self, parser):
        parser.add_argument("--uma-vez", action="store_true", help="processa a fila atual e sai")
        parser.add_argument(
            "--intervalo", type=float, default=3.0, help="segundos entre varreduras"
        )

    def handle(self, *args, **opcoes):
        if opcoes["uma_vez"]:
            self.stdout.write(f"{processamento.processar_fila()} item(ns) processado(s).")
            return
        self.stdout.write("Worker do cadastro rodando (Ctrl+C para parar).")
        try:
            while True:
                close_old_connections()
                try:
                    processamento.processar_fila()
                except Exception:  # noqa: BLE001 - o laço não pode morrer (banco fora do ar etc.)
                    self.stderr.write("Falha ao varrer a fila; tentando de novo.")
                time.sleep(opcoes["intervalo"])
        except KeyboardInterrupt:
            self.stdout.write("Worker encerrado.")
