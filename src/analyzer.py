import os
import logging
from datetime import datetime
import requests

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Analyzer:
    # As tuas ligas "VIP" (que enviam alerta para o Telegram)
    VIP_LEAGUES = [
        39, 140, 61, 78, 135, 94, 88, 71, 179, 144, 
        141, 40, 262, 301, 235, 253, 556, 128, 569, 307
    ]

    def __init__(self):
        self.api_url = "https://v3.football.api-sports.io"
        self.api_key = os.getenv("API_SPORTS_KEY")
        self.headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": "v3.football.api-sports.io"
        }
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        # Se tiveres LEAGUE_IDS no .env, usa esses como VIP, senão usa a lista padrão
        leagues_env = os.getenv("LEAGUE_IDS", "")
        if leagues_env:
            try:
                parsed = [int(x.strip()) for x in leagues_env.split(",") if x.strip().isdigit()]
                self.vip_leagues = sorted(list(set(parsed)))
            except Exception:
                self.vip_leagues = self.VIP_LEAGUES
        else:
            self.vip_leagues = self.VIP_LEAGUES

    def _get_api_data(self, endpoint, params):
        url = f"{self.api_url}/{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            if data.get("errors"):
                logger.warning(f"⚠️ API Info: {data['errors']}")
                return None
            return data.get("response", [])
        except Exception as e:
            logger.error(f"❌ Erro API ({endpoint}): {e}")
        return None

    def _get_last_fixture(self, team_id):
        # Busca último jogo TERMINADO
        params = {"team": team_id, "last": 1, "status": "FT-AET-PEN"}
        fixtures = self._get_api_data("fixtures", params)
        return fixtures[0] if fixtures else None

    def _get_team_statistics(self, team_id, league_id, season):
        params = {"team": team_id, "league": league_id, "season": season}
        return self._get_api_data("teams/statistics", params)

    def _calculate_real_stats(self, team_stats):
        if not team_stats: return 0.0, "N/A"
        played = team_stats.get("fixtures", {}).get("played", {}).get("total", 0)
        draws = team_stats.get("fixtures", {}).get("draws", {}).get("total", 0)
        clean_sheets = team_stats.get("clean_sheet", {}).get("total", 0)
        failed_to_score = team_stats.get("failed_to_score", {}).get("total", 0)
        
        if played == 0: return 0.0, "0/0"
        
        draw_rate = (draws / played) * 100
        trend_factor = ((clean_sheets + failed_to_score) / 2) / played * 100
        return draw_rate, trend_factor

    def _send_telegram_message(self, message):
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("⚠️ Telegram não configurado.")
            return
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        try:
            requests.post(url, data={"chat_id": self.telegram_chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
        except Exception as e:
            logger.error(f"Erro envio Telegram: {e}")

    def run_daily_analysis(self):
        today_str = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"🌍 Iniciando SCAN GLOBAL para a data: {today_str}")

        # 1. BUSCA GLOBAL (Sem filtro de liga para apanhar tudo)
        # Isto gasta apenas 1 Request e traz todos os jogos do mundo hoje
        params = {"date": today_str, "timezone": "Europe/Lisbon"}
        all_fixtures = self._get_api_data("fixtures", params) or []

        if not all_fixtures:
            logger.warning("❌ Nenhum jogo encontrado na API para hoje (Global).")
            return

        logger.info(f"📚 Total de jogos no mundo hoje: {len(all_fixtures)}")
        
        matches_checked = 0
        global_checks_counter = 0
        MAX_GLOBAL_CHECKS = 50  # Limite de segurança para equipas desconhecidas (poupar API)

        for fixture in all_fixtures:
            # Ignora jogos que já começaram
            if fixture['fixture']['status']['short'] not in ['NS', 'TBD']:
                continue

            league_id = fixture['league']['id']
            league_name = fixture['league']['name']
            
            # Detetar se é uma liga VIP (Configurada) ou "Outra"
            is_vip = league_id in self.vip_leagues
            
            # LÓGICA DE PROTEÇÃO DE QUOTA
            # Se não for VIP e já passámos o limite de testes "extra", ignora
            if not is_vip:
                if global_checks_counter >= MAX_GLOBAL_CHECKS:
                    continue
                global_checks_counter += 1

            # Tenta pegar a season correta do jogo
            try:
                match_season = fixture['league']['season']
            except:
                continue

            home = fixture["teams"]["home"]
            away = fixture["teams"]["away"]
            
            # Log de progresso (para veres no terminal que ele está a trabalhar)
            if matches_checked % 10 == 0:
                logger.info(f"🔎 Analisando jogo {matches_checked}: {home['name']} vs {away['name']} ({league_name})")
            matches_checked += 1

            # Verifica Home e Away
            for team_obj, side in [(home, 'Casa'), (away, 'Fora')]:
                team_id = team_obj['id']
                team_name = team_obj['name']

                # 2. Verifica último jogo (Gasta 1 Request)
                last_match = self._get_last_fixture(team_id)
                if not last_match: continue

                goals = last_match.get('goals', {})
                
                # SE DETECTAR 0x0
                if goals.get('home') == 0 and goals.get('away') == 0:
                    
                    # Se for VIP -> Processa tudo e manda Telegram
                    if is_vip:
                        stats = self._get_team_statistics(team_id, league_id, match_season)
                        draw_rate, defensive_trend = self._calculate_real_stats(stats)
                        
                        last_op = last_match['teams']['away']['name'] if last_match['teams']['home']['id'] == team_id else last_match['teams']['home']['name']
                        last_date = datetime.fromisoformat(last_match['fixture']['date'].replace('Z', '+00:00')).strftime('%d/%m')

                        msg = (
                            f"🚨 <b>ALERTA 0x0 DETECTADO</b>\n\n"
                            f"🏆 <b>{league_name}</b>\n"
                            f"⚽ {home['name']} vs {away['name']}\n"
                            f"🕒 {datetime.fromtimestamp(fixture['fixture']['timestamp']).strftime('%H:%M')}\n\n"
                            f"⚠️ <b>{team_name} ({side})</b> vem de 0x0!\n"
                            f"🆚 vs {last_op} ({last_date})\n\n"
                            f"📊 <b>Estatísticas (Season {match_season}):</b>\n"
                            f"• Taxa Empates: {draw_rate:.1f}%\n"
                            f"• Tendência 'Under': {defensive_trend:.1f}%\n"
                        )
                        self._send_telegram_message(msg)
                        logger.info(f"✅ TELEGRAM ENVIADO: {team_name} (Liga VIP)")
                    
                    # Se NÃO for VIP -> Apenas Log (O que tu pediste)
                    else:
                        logger.warning(f"👀 0x0 DETECTADO (Fora da Lista VIP): {team_name} na liga {league_name}. Adiciona a liga {league_id} para receberes alertas!")

        logger.info(f"🏁 Análise concluída. Jogos analisados: {matches_checked}. Extras verificados: {global_checks_counter}")

if __name__ == "__main__":
    bot = Analyzer()
    bot.run_daily_analysis()
