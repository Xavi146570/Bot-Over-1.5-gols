import os
import logging
from datetime import datetime
import requests

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Analyzer:
    TOP_20_LEAGUES = [
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

        # Ligas
        leagues_env = os.getenv("LEAGUE_IDS", "")
        if leagues_env:
            try:
                parsed = [int(x.strip()) for x in leagues_env.split(",") if x.strip().isdigit()]
                self.leagues = sorted(list(set(parsed)))
            except Exception:
                self.leagues = self.TOP_20_LEAGUES
        else:
            self.leagues = self.TOP_20_LEAGUES

    def _get_current_season(self):
        """
        Calcula a season. 
        Prioridade: 
        1. Variável de Ambiente (FIXED_SEASON) no ficheiro .env
        2. Cálculo automático baseado na data
        """
        # 1. Tenta ler do .env (ex: FIXED_SEASON=2024)
        env_season = os.getenv("FIXED_SEASON")
        
        if env_season:
            try:
                # Log apenas na primeira execução para não poluir
                return int(env_season)
            except ValueError:
                logger.error("❌ FIXED_SEASON no .env não é um número válido.")

        # 2. Fallback Automático
        now = datetime.now()
        if now.month < 8:
            return now.year - 1
        return now.year

    def _get_api_data(self, endpoint, params):
        url = f"{self.api_url}/{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # Log de erros da API (como o "Season required")
            if data.get("errors"):
                logger.warning(f"⚠️ API retornou erro/aviso: {data['errors']}")
                return None
                
            return data.get("response", [])
        except Exception as e:
            logger.error(f"❌ Erro ao buscar {endpoint}: {e}")
        return None

    def _get_last_fixture(self, team_id):
        # Busca o último jogo TERMINADO (status FT, AET, PEN) 
        # Importante: Evita pegar o jogo que está a decorrer agora (Live)
        params = {
            "team": team_id, 
            "last": 1,
            "status": "FT-AET-PEN" 
        }
        fixtures = self._get_api_data("fixtures", params)
        return fixtures[0] if fixtures else None

    def _get_team_statistics(self, team_id, league_id, season):
        params = {"team": team_id, "league": league_id, "season": season}
        stats = self._get_api_data("teams/statistics", params)
        return stats

    def _calculate_real_stats(self, team_stats):
        """Calcula estatísticas REAIS baseadas nos dados da API"""
        if not team_stats:
            return 0.0, "N/A"

        played = team_stats.get("fixtures", {}).get("played", {}).get("total", 0)
        draws = team_stats.get("fixtures", {}).get("draws", {}).get("total", 0)
        
        clean_sheets = team_stats.get("clean_sheet", {}).get("total", 0)
        failed_to_score = team_stats.get("failed_to_score", {}).get("total", 0)

        if played == 0:
            return 0.0, "0/0"

        draw_rate = (draws / played) * 100
        trend_factor = ((clean_sheets + failed_to_score) / 2) / played * 100
        
        return draw_rate, trend_factor

    def _send_telegram_message(self, message):
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("⚠️ Telegram não configurado. Mensagem não enviada.")
            return

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {"chat_id": self.telegram_chat_id, "text": message, "parse_mode": "HTML"}
        try:
            requests.post(url, data=payload, timeout=10)
        except Exception as e:
            logger.error(f"Erro Telegram: {e}")

    def run_daily_analysis(self):
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # Obtém a season (fixa pelo .env ou automática)
        current_season = self._get_current_season()
        
        logger.info(f"📅 Analisando jogos para: {today_str} (Season usada: {current_season})")

        matches_found = 0
        
        for league_id in self.leagues:
            # CORREÇÃO: Enviamos a 'season' para satisfazer a API
            params = {
                "date": today_str, 
                "league": league_id, 
                "season": current_season,
                "timezone": "Europe/Lisbon"
            }
            fixtures_today = self._get_api_data("fixtures", params)

            if not fixtures_today:
                continue

            matches_found += len(fixtures_today)
            logger.info(f"🔎 Liga {league_id}: {len(fixtures_today)} jogos")

            for fixture in fixtures_today:
                # Verifica apenas jogos que NÃO começaram (NS) ou data a definir (TBD)
                if fixture['fixture']['status']['short'] not in ['NS', 'TBD']:
                    continue

                home = fixture["teams"]["home"]
                away = fixture["teams"]["away"]
                league_name = fixture['league']['name']
                
                check_list = [(home, 'Casa'), (away, 'Fora')]

                for team_obj, side in check_list:
                    team_id = team_obj['id']
                    team_name = team_obj['name']

                    # Busca último jogo CONCLUÍDO
                    last_match = self._get_last_fixture(team_id)

                    if not last_match:
                        continue

                    # Verifica se foi 0-0
                    goals = last_match.get('goals', {})
                    if goals.get('home') == 0 and goals.get('away') == 0:
                        
                        # Busca stats
                        stats = self._get_team_statistics(team_id, league_id, current_season)
                        draw_rate, defensive_trend = self._calculate_real_stats(stats)
                        
                        last_opponent = last_match['teams']['away']['name'] if last_match['teams']['home']['id'] == team_id else last_match['teams']['home']['name']
                        last_date = datetime.fromisoformat(last_match['fixture']['date'].replace('Z', '+00:00')).strftime('%d/%m')

                        msg = (
                            f"🚨 <b>ALERTA 0x0 DETECTADO</b>\n\n"
                            f"🏆 <b>{league_name}</b>\n"
                            f"⚽ {home['name']} vs {away['name']}\n"
                            f"🕒 {datetime.fromtimestamp(fixture['fixture']['timestamp']).strftime('%H:%M')}\n\n"
                            f"⚠️ <b>{team_name} ({side})</b> vem de 0x0!\n"
                            f"🆚 vs {last_opponent} ({last_date})\n\n"
                            f"📊 <b>Estatísticas {current_season}:</b>\n"
                            f"• Taxa Empates: {draw_rate:.1f}%\n"
                            f"• Tendência 'Under': {defensive_trend:.1f}%\n"
                        )
                        
                        self._send_telegram_message(msg)
                        logger.info(f"✅ Alerta enviado: {team_name}")

        logger.info(f"🏁 Análise concluída. Total jogos vistos na API: {matches_found}")

if __name__ == "__main__":
    bot = Analyzer()
    bot.run_daily_analysis()
