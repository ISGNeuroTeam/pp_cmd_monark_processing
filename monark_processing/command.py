import math
import pandas as pd
from pp_exec_env.base_command import BaseCommand, Syntax


class MonarkProcessingCommand(BaseCommand):
    """
    Monark's raw data processing.
    Input: monark's dataset where rows are results of tests with encrypted FlyWheelLog
    """
    syntax = Syntax([])
    use_timewindow = False  # Does not require time window arguments
    idempotent = True  # Does not invalidate cache

    @staticmethod
    def hex_to_int(hex_str: str) -> int:
        """
        Converts hex string to int
        :param hex_str: input string in hex format "FFFFFFFF"
        """
        hex_reversed = hex_str[6:] + hex_str[4:6] + hex_str[2:4] + hex_str[0:2]
        return int(hex_reversed, 16)

    @staticmethod
    def calc_window(
            current_time: float, df: pd.DataFrame, type_measurement: str
    ) -> float:
        """
        Calculate power or rpm by slide mean window with variable size of window
        by condition
        :param current_time: center of time window
        :param df: dataframe with time series
        :param type_measurement: "power" or "rpm" because there is the difference between calculation method
        """
        sample_df = df[
            (df["time_test"] > current_time - 0.5)
            & (df["time_test"] < current_time + 0.5)
            ]
        result = 0.0
        if type_measurement == "power":
            result = round(
                (sample_df["power_brake"] + sample_df["power_kinetic"]).sum()
                / sample_df.shape[0],
                2,
            )
        elif type_measurement == "rpm":
            result = round(sample_df["rpm"].sum() / (sample_df.shape[0]), 2)
        else:
            AssertionError("Incorrect type_measurement. Possible are 'power' or 'rpm'")
        return result

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transform raw data by decryption of FlyWheelLog to timeseries.
        :param df: DataFrame to transform
        """
        self.log_progress("Start monark_process command")

        dfs = []
        for idx, row in df.iterrows():
            secs = []
            bufs = []
            for i in range(len(row["FlyWheelLog"]) // 8):
                buf = row["FlyWheelLog"][i * 8:(i + 1) * 8]
                bufs.append(buf)
                sec = self.hex_to_int(buf)
                secs.append(sec)

            res_df = pd.DataFrame({"timer": secs, "hex": bufs})
            res_df["Attempt"] = row["BoutNumber"]
            res_df["Created"] = row["_time"]
            res_df["LastName"] = row["LastName"]
            res_df["FirstName"] = row["FirstName"]
            res_df["Weight"] = row["PersonWeight"]
            res_df["Inertia"] = 0.91
            res_df["Magnets"] = round(14 / (52 * row["SamplingMagnets"] / 10000))
            res_df["BrakeWeight"] = row["BrakeWeight"]
            res_df["time_elapsed"] = (res_df["timer"] - res_df["timer"].iloc[0]) / 57600
            res_df["time_test"] = (
                                          res_df["time_elapsed"] + res_df["time_elapsed"].shift(1)
                                  ) / 2
            res_df["time_diff"] = res_df["timer"].diff()
            res_df["rpm"] = round(
                14 * 60 * 57600 / (res_df["Magnets"] * 52 * res_df["time_diff"])
            )
            res_df["time_test_diff"] = res_df["time_test"].diff()
            res_df["power_brake"] = (
                    res_df["BrakeWeight"]
                    * 9.81
                    * math.pi
                    * 0.514
                    / (res_df["Magnets"] * res_df["time_test_diff"])
            )
            res_df["power_kinetic"] = (
                    4
                    * math.pi ** 2
                    * 57600 ** 3
                    * res_df["Inertia"]
                    / (
                            res_df["Magnets"] ** 2
                            * (res_df["timer"] - res_df["timer"].shift(2))
                    )
                    * (
                            1 / (res_df["timer"] - res_df["timer"].shift(1)) ** 2
                            - 1 / (res_df["timer"].shift(1) - res_df["timer"].shift(2)) ** 2
                    )
            )
            res_df["time_recorded"] = round(
                res_df["time_elapsed"]
                - res_df["time_elapsed"].iloc[-1]
                + row["Duration"],
                2,
            )
            res_df = res_df.dropna().iloc[1:]
            res_df["power_centered"] = res_df["time_test"].apply(
                lambda x: self.calc_window(x, res_df, "power")
            )
            res_df["rpm_centered"] = res_df["time_test"].apply(
                lambda x: self.calc_window(x, res_df, "rpm")
            )
            dfs.append(res_df)

        self.log_progress("Monark dataset has been processed", stage=1, total_stages=1)
        return pd.concat(dfs)
