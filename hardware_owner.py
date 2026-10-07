"""One cooperating kit hardware process per computer; no rover traffic."""
import socket


class HardwareOwner:
    def __init__(self, port=18766):
        self.socket = socket.socket()
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.socket.bind(('127.0.0.1', port))
            self.socket.listen(1)
        except OSError as error:
            self.socket.close()
            raise OSError('Another kit hardware program is open (port 18766). Press STOP in its controller, verify stopped wheels, then Ctrl+C in its PowerShell window. Closing only the browser tab does not close the connection. Or use Read battery + IMU inside the stopped controller. No hardware connection opened by this program.') from error

    def close(self):
        self.socket.close()
