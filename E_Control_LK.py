#!/usr/bin/env python3

import socket
import sys
import time

DEBUG = True


class ModbusUDP:

    def __init__(self, ip, port=5001):
        self.ip = ip
        self.port = port
        self.timeout = 2

    def calculate_crc(self, data):

        crc = 0xFFFF

        for b in data:

            crc ^= b

            for _ in range(8):

                lsb = crc & 0x0001

                crc >>= 1

                if lsb:
                    crc ^= 0xA001

        return crc

    def build_request(
        self,
        slave_id,
        function_code,
        address,
        value
    ):

        request = bytearray(8)

        request[0] = slave_id
        request[1] = function_code

        request[2] = (address >> 8) & 0xFF
        request[3] = address & 0xFF

        request[4] = (value >> 8) & 0xFF
        request[5] = value & 0xFF

        crc = self.calculate_crc(request[:6])

        request[6] = crc & 0xFF
        request[7] = (crc >> 8) & 0xFF

        return bytes(request)

    def send_request(self, request):

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        sock.settimeout(self.timeout)

        try:

            if DEBUG:
                print(
                    "TX:",
                    request.hex(" ").upper()
                )

            sock.sendto(
                request,
                (self.ip, self.port)
            )

            response, _ = sock.recvfrom(1024)

            if DEBUG:
                print(
                    "RX:",
                    response.hex(" ").upper()
                )

            return response

        except socket.timeout:

            print(
                f"UDP receive timeout ({self.ip}:{self.port})"
            )

            return None

        except Exception as ex:

            print("Unexpected:", ex)

            return None

        finally:

            sock.close()

    def read_holding_registers(
        self,
        slave_id,
        address,
        count
    ):

        request = self.build_request(
            slave_id,
            0x03,
            address,
            count
        )

        response = self.send_request(request)

        if response is None:
            return None

        if len(response) < 5:
            return None

        if response[1] != 0x03:
            return None

        byte_count = response[2]

        values = []

        for i in range(byte_count // 2):

            value = (
                response[3 + i * 2] << 8
            ) | (
                response[4 + i * 2]
            )

            values.append(value)

        return values

    def write_single_register(
        self,
        slave_id,
        address,
        value
    ):

        request = self.build_request(
            slave_id,
            0x06,
            address,
            value
        )

        response = self.send_request(request)

        if response is None:
            return False

        if len(response) < 8:
            return False

        return response[1] == 0x06


class Chamber:

    SLAVE_ID = 1

    REG_STATUS = 30
    REG_CURRENT_TEMP = 101
    REG_SET_TEMP = 102
    REG_POWER = 105
    REG_SET_TEMP_CMD = 130

    def __init__(self, ip):

        self.modbus = ModbusUDP(ip)

    @staticmethod
    def reg_to_temp(value):

        if value > 60000:
            value -= 65536

        return value / 100.0

    @staticmethod
    def temp_to_reg(temp):

        value = int(round(temp * 100))

        if value < 0:
            value += 65536

        return value

    def get_status(self):

        result = self.modbus.read_holding_registers(
            self.SLAVE_ID,
            self.REG_STATUS,
            1
        )

        if result is None:
            return 99

        return result[0]

    def show_status(self):

        status = self.get_status()

        status_map = {
            0: "Idle",
            1: "Running",
            2: "Warning",
            3: "Error",
            4: "Maintain",
            99: "Communication Failed"
        }

        print(
            f"Status = {status} "
            f"({status_map.get(status,'Unknown')})"
        )

    def show_temp(self):

        value = self.modbus.read_holding_registers(
            self.SLAVE_ID,
            101,
            2
        )

        if value is None:
            return

        now_temp = self.reg_to_temp(value[0])
        set_temp = self.reg_to_temp(value[1])

        print(
            f"{time.strftime('%Y/%m/%d %H:%M:%S')} "
            f"=> Set {set_temp:.2f}C, "
            f"Now {now_temp:.2f}C"
        )

    def get_set_temp(self):

        value = self.modbus.read_holding_registers(
            self.SLAVE_ID,
            self.REG_SET_TEMP,
            1
        )

        if value is None:
            return None

        return self.reg_to_temp(value[0])

    def set_temp(self, temp):

        reg = self.temp_to_reg(temp)

        if not self.modbus.write_single_register(
            self.SLAVE_ID,
            self.REG_SET_TEMP_CMD,
            reg
        ):
            print("Set Temp Failed")
            return False

        retry = 0

        while retry < 3:

            verify = self.get_set_temp()

            if verify == temp:

                print(
                    f"{time.strftime('%Y/%m/%d %H:%M:%S')} "
                    f"=> Set temp to {verify:.2f}C"
                )

                return True

            retry += 1

            print(
                f"Mismatched set/read target temp, retry {retry}"
            )

        print("Error: Can't set temp correctly")
        return False

    def on(self):

        if self.modbus.write_single_register(
            self.SLAVE_ID,
            self.REG_POWER,
            1
        ):
            print("Chamber ON")
            return True

        return False

    def off(self):

        if self.modbus.write_single_register(
            self.SLAVE_ID,
            self.REG_POWER,
            0
        ):
            print("Chamber OFF")
            return True

        return False

    def wait_until_target(
        self,
        interval=120,
        tolerance=1.0,
        match_count=3
    ):

        reached = 0

        print(
            f"Check Timer={interval}s "
            f"Tolerance={tolerance}C "
            f"Count={match_count}"
        )

        while True:

            value = self.modbus.read_holding_registers(
                self.SLAVE_ID,
                101,
                2
            )

            if value is None:

                reached = 0
                time.sleep(interval)
                continue

            now_temp = self.reg_to_temp(value[0])
            set_temp = self.reg_to_temp(value[1])

            print(
                f"{time.strftime('%Y/%m/%d %H:%M:%S')} "
                f"=> Set {set_temp:.2f}, "
                f"Now {now_temp:.2f}"
            )

            delta = set_temp - now_temp

            if -tolerance < delta < tolerance:

                reached += 1

                print(
                    f"Matched "
                    f"{reached}/{match_count}"
                )

            else:

                reached = 0

            if reached >= match_count:

                print(
                    "Chamber is reaching the setting!"
                )

                return True

            time.sleep(interval)


def show_help():

    print("""
Chamber Control Tool

Chamber (LK) Modbus(Ethernet UDP 5001): chamber.py [IP] [option]

IP        : Specify which IP address to control

option    :

        -o                          Turn on Chamber. (1st priority)
        -f                          Turn off Chamber. (2nd priority)
        -q                          Query the temp.
        -s [VALUE]                  Set temperature value.

        -d                          Use default setting to reach the temperature.
        -t [VALUE]                  Set Check Timer (s), default is 120.
        -l [VALUE]                  Set Tolerance Value (+-) C, default is 1.
        -r [VALUE]                  Set Count Time of temperature compare,
                                    default is 3.

Examples :

        Query chamber temperature

                python3 chamber.py 192.168.1.100 -q

        Set chamber to -40C and turn on

                python3 chamber.py 192.168.1.100 -s -40 -o

        Set chamber to -40C and wait

                python3 chamber.py 192.168.1.100 -s -40 -o -d

""")

    sys.exit(0)


def main():

    if len(sys.argv) < 2:
        show_help()

    if sys.argv[1].lower() in ["-h", "--help"]:
        show_help()

    ip = sys.argv[1]

    chamber = Chamber(ip)

    run_default = False

    interval = 120
    tolerance = 1.0
    match_count = 3

    chamber.show_status()

    i = 2

    while i < len(sys.argv):

        arg = sys.argv[i].upper()

        if arg == "-Q":

            chamber.show_temp()

        elif arg == "-S":

            chamber.set_temp(
                float(sys.argv[i + 1])
            )

            i += 1

        elif arg == "-O":

            chamber.on()

        elif arg == "-F":

            chamber.off()

        elif arg == "-D":

            run_default = True

        elif arg == "-T":

            interval = int(sys.argv[i + 1])
            i += 1

        elif arg == "-L":

            tolerance = float(sys.argv[i + 1])
            i += 1

        elif arg == "-R":

            match_count = int(sys.argv[i + 1])
            i += 1

        else:

            print(
                f"Unknown parameter: {sys.argv[i]}"
            )

        i += 1

    if run_default:

        chamber.wait_until_target(
            interval=interval,
            tolerance=tolerance,
            match_count=match_count
        )


if __name__ == "__main__":
    main()