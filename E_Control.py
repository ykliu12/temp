#!/usr/bin/env python3

from pymodbus.client import ModbusUdpClient
import sys
import time


class Chamber:
    SLAVE_ID = 1

    REG_STATUS = 30
    REG_CURRENT_TEMP = 101
    REG_SET_TEMP = 102
    REG_POWER = 105
    REG_SET_TEMP_CMD = 130

    def __init__(self, ip, port=5001):
        self.ip = ip
        self.port = port
        self.client = ModbusUdpClient(host=ip, port=port)

    def connect(self):
        return self.client.connect()

    def close(self):
        self.client.close()

    @staticmethod
    def reg_to_temp(value):
        if value > 32767:
            value -= 65536
        return value / 100.0

    @staticmethod
    def temp_to_reg(temp):
        value = int(round(temp * 100))

        if value < 0:
            value += 65536

        return value

    def get_status(self):
        result = self.client.read_holding_registers(
            address=self.REG_STATUS,
            count=1,
            slave=self.SLAVE_ID
        )

        if result.isError():
            return 99

        return result.registers[0]

    def get_current_temp(self):
        result = self.client.read_holding_registers(
            address=self.REG_CURRENT_TEMP,
            count=1,
            slave=self.SLAVE_ID
        )

        if result.isError():
            raise Exception("Read current temperature failed")

        return self.reg_to_temp(result.registers[0])

    def get_set_temp(self):
        result = self.client.read_holding_registers(
            address=self.REG_SET_TEMP,
            count=1,
            slave=self.SLAVE_ID
        )

        if result.isError():
            raise Exception("Read target temperature failed")

        return self.reg_to_temp(result.registers[0])

    def show_temp(self):
        current = self.get_current_temp()
        target = self.get_set_temp()

        print(
            f"{time.strftime('%Y/%m/%d %H:%M:%S')} "
            f"=> Set {target:.2f}C, Now {current:.2f}C"
        )

    def set_temp(self, temp):

        value = self.temp_to_reg(temp)

        self.client.write_register(
            address=self.REG_SET_TEMP_CMD,
            value=value,
            slave=self.SLAVE_ID
        )

        time.sleep(1)

        verify = self.get_set_temp()

        print(
            f"{time.strftime('%Y/%m/%d %H:%M:%S')} "
            f"=> Set Temp {verify:.2f}C"
        )

    def on(self):
        self.client.write_register(
            address=self.REG_POWER,
            value=1,
            slave=self.SLAVE_ID
        )

        print("Chamber ON")

    def off(self):
        self.client.write_register(
            address=self.REG_POWER,
            value=0,
            slave=self.SLAVE_ID
        )

        print("Chamber OFF")

    def wait_until_target(
            self,
            tolerance=1.0,
            interval=60,
            match_count=3):

        matched = 0

        print(
            f"Waiting for temperature "
            f"(Tolerance ±{tolerance}C, "
            f"Interval {interval}s, "
            f"Match {match_count})"
        )

        while True:

            current = self.get_current_temp()
            target = self.get_set_temp()

            diff = abs(target - current)

            print(
                f"{time.strftime('%Y/%m/%d %H:%M:%S')} "
                f"=> Set {target:.2f}C, "
                f"Now {current:.2f}C"
            )

            if diff <= tolerance:
                matched += 1
                print(f"Matched {matched}/{match_count}")
            else:
                matched = 0

            if matched >= match_count:
                print("Target temperature reached.")
                return

            time.sleep(interval)


def show_help():
    print(r"""
==================================================
 Chamber Control Tool (Modbus UDP)
==================================================

Usage:

    python3 chamber.py <IP> [Options]

Options:

    -Q
        Show chamber temperature

    -S <Temp>
        Set target temperature

    -O
        Turn chamber ON

    -F
        Turn chamber OFF

    -W
        Wait until temperature reaches target

    -T <Seconds>
        Check interval
        Default = 60

    -R <Count>
        Consecutive match count
        Default = 3

    -L <Tolerance>
        Temperature tolerance
        Default = 1.0

Examples:

    Show temperature

        python3 chamber.py 192.168.1.100 -Q

    Set temperature

        python3 chamber.py 192.168.1.100 -S 25

    Set -40C

        python3 chamber.py 192.168.1.100 -S -40

    Turn ON

        python3 chamber.py 192.168.1.100 -O

    Turn OFF

        python3 chamber.py 192.168.1.100 -F

    Set and Turn ON

        python3 chamber.py 192.168.1.100 -S -40 -O

    Turn ON and Wait

        python3 chamber.py 192.168.1.100 -S -40 -O -W

    Wait with interval 30 seconds

        python3 chamber.py 192.168.1.100 -S -40 -O -W -T 30

==================================================
Register Map

30      Chamber Status
101     Current Temperature
102     Target Temperature
105     Chamber ON/OFF
130     Set Temperature

==================================================
""")

    sys.exit(0)


def main():

    if len(sys.argv) < 2:
        show_help()

    if sys.argv[1] in ["-h", "--help"]:
        show_help()

    ip = sys.argv[1]

    query_temp = False
    power_on = False
    power_off = False
    wait_mode = False

    temperature = None

    interval = 60
    tolerance = 1.0
    match_count = 3

    i = 2

    while i < len(sys.argv):

        arg = sys.argv[i].upper()

        if arg == "-Q":
            query_temp = True

        elif arg == "-O":
            power_on = True

        elif arg == "-F":
            power_off = True

        elif arg == "-W":
            wait_mode = True

        elif arg == "-S":
            temperature = float(sys.argv[i + 1])
            i += 1

        elif arg == "-T":
            interval = int(sys.argv[i + 1])
            i += 1

        elif arg == "-R":
            match_count = int(sys.argv[i + 1])
            i += 1

        elif arg == "-L":
            tolerance = float(sys.argv[i + 1])
            i += 1

        else:
            print(f"Unknown parameter: {sys.argv[i]}")
            return

        i += 1

    chamber = Chamber(ip)

    if not chamber.connect():
        print(f"Cannot connect to {ip}:5001")
        return

    try:

        status = chamber.get_status()

        print(f"Status = {status}")

        if query_temp:
            chamber.show_temp()

        if temperature is not None:
            chamber.set_temp(temperature)

        if power_on:
            chamber.on()

        if power_off:
            chamber.off()

        if wait_mode:
            chamber.wait_until_target(
                tolerance=tolerance,
                interval=interval,
                match_count=match_count
            )

    finally:
        chamber.close()


if __name__ == "__main__":
    main()