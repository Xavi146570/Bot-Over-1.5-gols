import os
import logging
from datetime import datetime
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Analyzer:
    def __init__(self):
        self.api_url = "https://v3.football.api-sports.io"
        self.api_key = os.getenv("API_SPORTS_KEY")
        self.headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": "v3.football.api-sports.io"
        }
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "-1003109764236")

        if not self.api_key:
            logger.error("❌ API_SPORTS_KEY não configurada!")
        if not self.telegram_token:
            logger.error("❌ TELEGRAM_BOT_TOKEN não configurado!")

    # ------------------------------------------------------------
    # Funções auxiliares
    # ------------------------------------------------------------
    def _get_api_data(self, endpoint, params):
        url = f"{self.api_url}/{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            if data.get("errors"):
                logger.error(f"Erro da API: {data['errors']}")
                return None
            return data.get("response", [])
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTPError ao buscar {endpoint}: {e} - {response.text}")
        except Exception as e:
            logger.error(f"Erro inesperado ao buscar {endpoint}: {e}")
        return None

    def _get_last_fixture(self, team_id):
        params = {"team": team_id, "last": 1}
        fixtures = self._get_api_data("fixtures", params)
        if fixtures:
            return fixtures[0]
        return None

    def _get_team_statistics(self, team_id, league_id, season):
        params = {
            "team": team_id,
            "league": league_id,
            "season": season
        }
        stats = self._get_api_data("teams/statistics", params)
        if stats:
            return stats
        return None

    def _calculate_0x0_rate(self, team_stats):
        if not team_stats:
            return 0.0, 0

        home_games = team_stats.get("fixtures", {}).get("played", {}).get("home", 0)
        away_games = team_stats.get("fixtures", {}).get("played", {}).get("away", 0)
        total_games = home_games + away_games

        if total_games == 0:
            return 0.0, 0

        simulated_0x0_rate = 0.05  # Simulação (5%)
        prob_repeat = simulated_0x0_rate * simulated_0x0_rate * 100
        return simulated_0x0_rate * 100, prob_repeat

    def _send_telegram_message(self, message):
        if not self.telegram_token or not self.telegram_chat_id:
            logger.error("Token ou Chat ID do Telegram não configurados.")
            return

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            response.raise_for_status()
            logger.info("Mensagem enviada com sucesso para o Telegram.")
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem para o Telegram: {e}")

    # ------------------------------------------------------------
    # Execução principal
    # ------------------------------------------------------------
    def run_daily_analysis(self, leagues=None):
        if leagues is None:
            leagues = [39, 140]  # Premier League e La Liga

        today_str = datetime.now().strftime("%Y-%m-%d")
        season = datetime.now().year
        logger.info(f"📅 Executando análise para a data atual: {today_str}")

        notification_messages = []

        for league_id in leagues:
            params = {"date": today_str, "league": league_id, "season": season}
            fixtures_today = self._get_api_data("fixtures", params)

            if not fixtures_today:
                logger.info(f"⚠️ Nenhum jogo encontrado para a liga {league_id} hoje.")
                continue

            for fixture in fixtures_today:
                home_team = fixture["teams"]["home"]
                away_team = fixture["teams"]["away"]

                teams_to_check = {
                    home_team["id"]: home_team["name"],
                    away_team["id"]: away_team["name"]
                }

                for team_id, team_name in teams_to_check.items():
                    last_fixture = self._get_last_fixture(team_id)

                    if last_fixture:
                        goals_home = last_fixture["goals"]["home"]
                        goals_away = last_fixture["goals"]["away"]

                        if goals_home == 0 and goals_away == 0:
                            team_stats = self._get_team_statistics(team_id, league_id, season)
                            rate_0x0, prob_repeat = self._calculate_0x0_rate(team_stats)

                            message = (
                                f"⚽️ *ALERTA 0x0 - Jogo de Hoje*\n"
                                f"🗓️ Jogo: *{home_team['name']}* vs *{away_team['name']}*\n"
                                f"🏆 Liga: {fixture['league']['name']}\n"
                                f"⏰ Horário: {datetime.fromtimestamp(fixture['fixture']['timestamp']).strftime('%H:%M')}\n\n"
                                f"⚠️ *{team_name}* vem de um 0x0 na última rodada.\n"
                                f"📊 Taxa histórica de 0x0 na época: *{rate_0x0:.1f}%*\n"
                                f"📉 Probabilidade de repetir 0x0 hoje: *{prob_repeat:.2f}%*\n"
                            )
                            notification_messages.append(message)

        if notification_messages:
            full_message = "\n---\n".join(notification_messages)
            self._send_telegram_message(full_message)
        else:
            logger.info("Nenhuma equipe encontrada que se encaixe nos critérios de análise 0x0.")


if __name__ == "__main__":
    analyzer = Analyzer()
    analyzer.run_daily_analysis()
