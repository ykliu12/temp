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
        value_or_count
    ):

        request = bytearray(8)

        request[0] = slave_id
        request[1] = function_code

        request[2] = (address >> 8) & 0xFF
        request[3] = address & 0xFF

        request[4] = (value_or_count >> 8) & 0xFF
        request[5] = value_or_count & 0xFF

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

            response, addr = sock.recvfrom(1024)

            if DEBUG:
                print(
                    "RX:",
                    response.hex(" ").upper()
                )

            return response

        except socket.timeout:

            print(
                f"UDP receive timeout "
                f"({self.ip}:{self.port})"
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

        values = []

        byte_count = response[2]

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

        reg = int(round(temp * 100))

        if reg < 0:
            reg += 65536

        return reg

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

        result = self.modbus.read_holding_registers(
            self.SLAVE_ID,
            101,
            2
        )

        if result is None:
            return

        current = self.reg_to_temp(result[0])
        target = self.reg_to_temp(result[1])

        print(
            f"{time.strftime('%Y/%m/%d %H:%M:%S')} "
            f"=> Set {target:.2f}C, "
            f"Now {current:.2f}C"
        )

    def get_set_temp(self):

        result = self.modbus.read_holding_registers(
            self.SLAVE_ID,
            102,
            1
        )

        if result is None:
            return None

        return self.reg_to_temp(result[0])

    def set_temp(self, temp):

        reg = self.temp_to_reg(temp)

        if not self.modbus.write_single_register(
            self.SLAVE_ID,
            self.REG_SET_TEMP_CMD,
            reg
        ):
            print("Set Temp Failed")
            return

        retry = 0

        while retry < 3:

            verify = self.get_set_temp()

            if verify == temp:

                print(
                    f"{time.strftime('%Y/%m/%d %H:%M:%S')} "
                    f"=> Set Temp to {verify:.2f}C"
                )

                return

            retry += 1

            print(
                f"Mismatched set/read "
                f"target temp, retry {retry}"
            )

        print("Error: Can't set temp correctly")

    def on(self):

        if self.modbus.write_single_register(
            self.SLAVE_ID,
            self.REG_POWER,
            1
        ):
            print("Chamber ON")

    def off(self):

        if self.modbus.write_single_register(
            self.SLAVE_ID,
            self.REG_POWER,
            0
        ):
            print("Chamber OFF")


def show_help():

    print("""
=================================================

Chamber Control Tool

Usage:

    python3 chamber.py <IP> [OPTION]

OPTION

    -Q
        Query Temperature

    -S <Temp>
        Set Temperature

    -O
        Chamber ON

    -F
        Chamber OFF

Examples

    Query Temp

        python3 chamber.py 192.168.1.100 -Q

    Set 25C

        python3 chamber.py 192.168.1.100 -S 25

    Set -40C

        python3 chamber.py 192.168.1.100 -S -40

    Turn ON

        python3 chamber.py 192.168.1.100 -O

    Turn OFF

        python3 chamber.py 192.168.1.100 -F

    Set -40C and ON

        python3 chamber.py 192.168.1.100 -S -40 -O

=================================================
""")

    sys.exit(0)


def main():

    if len(sys.argv) < 2:
        show_help()

    if sys.argv[1] in ["-h", "--help"]:
        show_help()

    ip = sys.argv[1]

    chamber = Chamber(ip)

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

        else:

            print(
                f"Unknown parameter: {sys.argv[i]}"
            )

        i += 1


if __name__ == "__main__":
    main()