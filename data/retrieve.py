__author__ = "Wren J. R. (uberfastman)"
__email__ = "wrenjr@yahoo.com"

from collections import defaultdict
import os
import logging
import itertools
from concurrent.futures import ThreadPoolExecutor
# import sys

from yffpy.models import Game, League, Settings, Standings

from calculate.bad_boy_stats import BadBoyStats
from calculate.beef_stats import BeefStats
from calculate.playoff_probabilities import PlayoffProbabilities

logger = logging.getLogger(__name__)
# Suppress YahooFantasyFootballQuery debug logging
logging.getLogger("yffpy.query").setLevel(level=logging.INFO)


def user_week_input_validation(config, week, retrieved_current_week):
    # user input validation
    if week:
        chosen_week = week
    else:
        chosen_week = config.get("Fantasy_Football_Report_Settings", "chosen_week")
    try:
        current_week = retrieved_current_week
        if chosen_week == "default":
            if (int(current_week) - 1) > 0:
                chosen_week = str(int(current_week) - 1)
            else:
                first_week_incomplete = input(
                    "The first week of the season is not yet complete. "
                    "Are you sure you want to generate a report for an incomplete week? (y/n) -> ")
                if first_week_incomplete == "y":
                    chosen_week = current_week
                elif first_week_incomplete == "n":
                    raise ValueError("It is recommended that you NOT generate a report for an incomplete week.")
                else:
                    raise ValueError("Please only select 'y' or 'n'. Try running the report generator again.")

        elif 0 < int(chosen_week) < 18:
            if 0 < int(chosen_week) <= int(current_week) - 1:
                chosen_week = chosen_week
            else:
                incomplete_week = input(
                    "Are you sure you want to generate a report for an incomplete week? (y/n) -> ")
                if incomplete_week == "y":
                    chosen_week = chosen_week
                elif incomplete_week == "n":
                    raise ValueError("It is recommended that you NOT generate a report for an incomplete week.")
                else:
                    raise ValueError("Please only select 'y' or 'n'. Try running the report generator again.")
        else:
            raise ValueError("You must select either 'default' or an integer from 1 to 17 for the chosen week.")
    except ValueError:
        raise ValueError("You must select either 'default' or an integer from 1 to 17 for the chosen week.")

    return chosen_week


class RetrieveYffLeagueData(object):

    def __init__(self, config, yahoo_data, yahoo_query, yahoo_game_id, yahoo_league_id, data_dir, selected_week):

        self.config = config
        self.data_dir = data_dir

        if yahoo_game_id and yahoo_game_id != "nfl":
            yahoo_fantasy_game = yahoo_data.retrieve(str(yahoo_game_id) + "-game-metadata",
                                                     yahoo_query.get_game_metadata_by_game_id,
                                                     params={"game_id": yahoo_game_id},
                                                     data_type_class=Game)
        else:
            yahoo_fantasy_game = yahoo_data.retrieve("current-game-metadata",
                                                     yahoo_query.get_current_game_metadata,
                                                     data_type_class=Game)

        self.league_key = yahoo_fantasy_game.game_key + ".l." + yahoo_league_id
        self.season = yahoo_fantasy_game.season

        # print(self.league_key)
        # sys.exit()

        def _get_metadata():
            return yahoo_data.retrieve(str(yahoo_league_id) + "-league-metadata",
                                            yahoo_query.get_league_metadata,
                                            data_type_class=League,
                                            new_data_dir=os.path.join(self.data_dir,
                                                                    str(self.season),
                                                                self.league_key))

        def _get_settings():
            return yahoo_data.retrieve(str(yahoo_league_id) + "-league-settings",
                                        yahoo_query.get_league_settings,
                                        data_type_class=Settings,
                                        new_data_dir=os.path.join(self.data_dir,
                                                                str(self.season),
                                                                self.league_key))                    
        
        print("Getting league metadata and settings...")
        with ThreadPoolExecutor() as executor:
            funcs = [
                {
                    "name": "league_metadata",
                    "func": _get_metadata
                },
                {
                    "name": "league_settings",
                    "func": _get_settings
                }
            ]
            for name in executor.map(self._load_data, funcs):
                # print(name + " finished")
                pass
        
        self.name = self.league_metadata.name

        # print(self.name)
        # print(self.league_metadata)
        # sys.exit()
        # print(self.league_settings)
        # sys.exit()

        self.playoff_slots = self.league_settings.num_playoff_teams
        self.num_regular_season_weeks = int(self.league_settings.playoff_start_week) - 1
        self.roster_positions = self.league_settings.roster_positions
        self.roster_positions_by_type = self.get_roster_slots(self.roster_positions)

        # print(self.playoff_slots)
        # print(self.num_regular_season_weeks)
        # print(self.roster_positions)
        # sys.exit()

        def _get_standings():
            return yahoo_data.retrieve(str(yahoo_league_id) + "-league-standings",
                                            yahoo_query.get_league_standings,
                                            data_type_class=Standings,
                                            new_data_dir=os.path.join(self.data_dir,
                                                                    str(self.season),
                                                                    self.league_key))
        # print(self.league_standings_data)
        # sys.exit()

        def _get_teams():
            return yahoo_data.retrieve(str(yahoo_league_id) + "-league-teams",
                                        yahoo_query.get_league_teams,
                                        new_data_dir=os.path.join(self.data_dir,
                                                                str(self.season),
                                                                self.league_key))
        # print(self.teams)
        # sys.exit()

        print("Getting teams and standings...")
        with ThreadPoolExecutor() as executor:
            funcs = [
                {
                    "name": "standings",
                    "func": _get_standings
                },
                {
                    "name": "teams",
                    "func": _get_teams
                }
            ]
            for name in executor.map(self._load_data, funcs):
                # print(name + " finished")
                pass

        # validate user selection of week for which to generate report
        self.chosen_week = user_week_input_validation(self.config, selected_week, self.league_metadata.current_week)

        print("Getting matchups...")
        # run yahoo queries requiring chosen week
        with ThreadPoolExecutor() as executor:
            def _get_week(week):
                # print("querying " + week)
                return {
                    "week": week,
                    "result": yahoo_data.retrieve("week_" + str(self.chosen_week) + "-matchups_by_week",
                                        yahoo_query.get_league_matchups_by_week,
                                        params={"chosen_week": week},
                                        new_data_dir=os.path.join(self.data_dir,
                                                                str(self.season),
                                                                self.league_key,
                                                                "week_" + week))
                }

            self.matchups_by_week = {}
            weeks = [str(w) for w in range(1, self.num_regular_season_weeks + 1)]

            for response in executor.map(_get_week, weeks):
                self.matchups_by_week[response["week"]] = response["result"]
                # print(response["week"] + " finished")
            
        # print(self.matchups_by_week)
        # sys.exit()

        print("Getting rosters...")
        with ThreadPoolExecutor() as executor:
            def _get_roster(query):
                team = query["team"]
                week = query["week"]
                team_id = str(team.get("team").team_id)
                # print("querying {0}:{1}".format(week, team_id))
                return {
                    "week": week,
                    "team": team,
                    "result": yahoo_data.retrieve(
                            team_id + "-" +
                            str(team.get("team").name.decode("utf-8")).replace(" ", "_") + "-roster_positions",
                            yahoo_query.get_team_roster_player_stats_by_week,
                            params={"team_id": team_id, "chosen_week": week},
                            new_data_dir=os.path.join(
                                self.data_dir, str(self.season), self.league_key, "week_" + week, "rosters_by_week")
                        )
                }

            self.rosters_by_week = defaultdict(dict)

            weeks = [str(w) for w in range(1, int(self.chosen_week) + 1)]
            
            # build combinations of teams/weeks to query
            query = [{"week": w, "team": t} for w in weeks for t in self.teams]

            for response in executor.map(_get_roster, query):
                week = response["week"]
                team_id = response["team"].get("team").team_id
                self.rosters_by_week[week][team_id] = response["result"]

                # print("{0}:{1} finished".format(week, team_id))

        # print(self.rosters_by_week.keys())
        # sys.exit()

        self.playoff_probs = self.get_playoff_probs()

    def _load_data(self, request):
        self.__setattr__(request["name"], request["func"]() )
        return request["name"]

    @staticmethod
    def get_roster_slots(roster_positions):

        position_counts = defaultdict(int)
        positions_active = []
        positions_flex = []
        positions_bench = ["BN", "IR"]
        for roster_position in roster_positions:

            roster_position = roster_position.get("roster_position")

            position_name = roster_position.position
            position_count = int(roster_position.count)

            count = position_count
            while count > 0:
                if position_name not in positions_bench:
                    positions_active.append(position_name)
                count -= 1

            if position_name == "W/R":
                positions_flex = ["WR", "RB"]
            if position_name == "W/R/T":
                positions_flex = ["WR", "RB", "TE"]
            if position_name == "Q/W/R/T":
                positions_flex = ["QB", "WR", "RB", "TE"]

            if "/" in position_name:
                position_name = "FLEX"

            position_counts[position_name] += position_count

        roster_positions_by_type = {
            "position_counts": position_counts,
            "positions_active": positions_active,
            "positions_flex": positions_flex,
            "positions_bench": positions_bench
        }

        # print(self.roster_positions)
        # sys.exit()

        return roster_positions_by_type

    def get_playoff_probs(self, save_data=False, dev_offline=False, recalculate=True):
        # TODO: UPDATE USAGE OF recalculate PARAM (could use self.dev_offline)
        playoff_probs = PlayoffProbabilities(
            self.config.getint("Fantasy_Football_Report_Settings", "num_playoff_simulations"),
            self.num_regular_season_weeks,
            self.playoff_slots,
            data_dir=os.path.join(self.data_dir, str(self.season), self.league_key),
            save_data=save_data,
            recalculate=recalculate
        )
        # print(self.playoff_probs_data)
        # sys.exit()
        return playoff_probs

    def get_bad_boy_stats(self, save_data=False, dev_offline=False):
        bad_boy_stats = BadBoyStats(
            os.path.join(self.data_dir, str(self.season), self.league_key),
            save_data=save_data,
            dev_offline=dev_offline)
        # print(self.bad_boy_stats)
        # sys.exit()
        return bad_boy_stats

    def get_beef_stats(self, save_data=False, dev_offline=False):

        beef_stats = BeefStats(
            os.path.join(self.data_dir, str(self.season), self.league_key),
            save_data=save_data,
            dev_offline=dev_offline)
        # print(self.beef_rank)
        # sys.exit()
        return beef_stats
