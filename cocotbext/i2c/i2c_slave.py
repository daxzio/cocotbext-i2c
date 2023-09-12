"""

Copyright (c) 2020 Alex Forencich

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

"""

import logging

from cocotb import start_soon
from cocotb.triggers import RisingEdge, FallingEdge, Timer
# from cocotb.binary import BinaryValue
# from cocotb.types import Logic
from .version import __version__


class I2cSlave:

    def __init__(self, sda_i=None, sda_o=None, scl_o=None, addr=0x45, speed=400e3, *args, **kwargs):
        self.log = logging.getLogger(f"cocotb.{sda_i._path}")
        #self.sda = sda
        #self.scl = scl
        if addr > 0x7f:
            self.log.warning(f"I2C can only accept addresses of 7 bits: 0x{addr}")
            raise Exception(f"I2C can only accept addresses of 7 bits: 0x{addr}")
        self.sda_i = sda_i
        self.sda_o = sda_o
        self.scl_o = scl_o
        self.addr = addr & 0x7f
        self.speed = speed
        
        self.start = False
        self.stop = False
        self.bit_pos = 0
        self.address_phase = False
        self.read_phase = False
        self.write_phase = False
        self.recv_addr = None
        
        self.val = 0x81

        self.log.info("I2C Slave")
        self.log.info("cocotbext-i2c version %s", __version__)
        self.log.info("Copyright (c) 2020 Alex Forencich")
        self.log.info("https://github.com/alexforencich/cocotbext-i2c")
        self.log.info("https://github.com/alexforencich/cocotbext-i2c")

        super().__init__(*args, **kwargs)

        self.bus_active = False

#         if self.sda is not None:
#             #self.sda.setimmediatevalue(BinaryValue('z'))
#             #self.sda.value = 1
#             #self.sda.value = BinaryValue("Z")
#             self.sda.setimmediatevalue(Logic("Z"))
        
        
        if self.sda_i is not None:
            self.sda_i.setimmediatevalue(1)

#         if self.scl_o_i is not None:
#             self.scl_o_i.setimmediatevalue(0)

        self.log.info("I2C slave configuration:")
        self.log.info("  Speed: %d bps", self.speed)

#         self._bit_t = Timer(int(1e9/self.speed), 'ns')
#         self._half_bit_t = Timer(int(1e9/self.speed/2), 'ns')

        self._run_cr = None
        self._restart()

    def _set_sda(self, val):
        if self.sda_o is not None:
            self.sda_o.value = val
        else:
            self.sda.value = val
            # self.sda <= BinaryValue('z') if val else 0

    async def wait_bit(self):
        await Timer(int(1e9/self.speed), units='ns')
    
    async def wait_half_bit(self):
        await Timer(int(1e9/self.speed/2), units='ns')
    
    async def wait_quarter_bit(self):
        await Timer(int(1e9/self.speed/4), units='ns')

    async def wait_clock_dly(self):
        await Timer(int(1e9/self.speed/4), units='ns')
    
    def _restart(self):
#         if self._run_cr is not None:
#             self._run_cr.kill()
#         self._run_cr = start_soon(self._run())
        start_soon(self._detect_start())
        start_soon(self._detect_stop())
        start_soon(self._falling_scl())
        start_soon(self._rising_scl())

    async def _detect_start(self):
        while True:
            await FallingEdge(self.sda_o)
            if 1 == self.scl_o.value:
                self.log.info("Start bit detected")
                self.start = True
                self.bit_pos = 0
                self.address_phase = True
                self.active = False
    
    async def _detect_stop(self):
        while True:
            await RisingEdge(self.sda_o)
            if 1 == self.scl_o.value:
                self.log.info("Stop bit detected")
                self.stop = True
    
    async def _falling_scl(self):
        while True:
            await FallingEdge(self.scl_o)
            await self.wait_clock_dly()
            self.sda_i.value = 1
                        
            if self.start or not self.bit_pos == 0:
                if self.bit_pos == 9:
                    self.bit_pos = 1
                else:
                    self.bit_pos += 1
                self.start = False
            
            if (self.address_phase and self.active) or self.write_phase:
                if self.bit_pos == 9:
                    self.sda_i.value = 0
            elif self.read_phase:
                if not 0 == self.bit_pos and not self.bit_pos >= 9:
                    #self.sda_i.value = 1
                    self.sda_i.value = (self.val >> (8-self.bit_pos)) & 0x1

    async def _rising_scl(self):
        while True:
            await RisingEdge(self.scl_o)
            if not 0 == self.bit_pos and not self.bit_pos >= 9:
                if 1 == self.bit_pos:
                    self.recv_byte = 0
                self.recv_byte |= (self.sda_o.value << (8-self.bit_pos))
                
                if self.bit_pos == 8:
                    if self.address_phase:
                        self.read_phase = False
                        self.write_phase = False
                        self.recv_addr = self.recv_byte >> 1
                        self.active = (self.recv_addr == self.addr)
                        if 1 == self.sda_o.value:
                            self.read_phase = True
                            access_type = "Read"
                        else:
                            self.write_phase = True
                            access_type = "Write"
                    if self.address_phase or self.write_phase:
                        self.log.info(f"Received: 0x{self.recv_byte:02x} {access_type} {self.active}")
            
            if self.read_phase and not self.address_phase and self.bit_pos == 9:
                self.log.info(f"Transmit: 0x{self.val:02x} ACK {self.sda_o.value}")
                self.val += 1
            if self.bit_pos == 9:
                self.address_phase = False

    
#     async def _run(self):
#         self.active = False
#         #self.sda_o_dly = None
# 
#         while True:
#             await self._half_bit_t
#             if self.start:
#                 await self._half_bit_t
#                 #self.sda_i.value = 0
# #                 await self._half_bit_t
# #                 self.sda_i.value = 0
#                 await self._bit_t
#                 await self._bit_t
#                 await self._bit_t
#                 await self._bit_t
#                 await self._bit_t
#                 await self._bit_t
#                 await self._bit_t
#                 await self._bit_t
#                 self.sda_i.value = 0
#                 #self.start = False
#                 await self._bit_t
#                 self.sda_i.value = 1


#             self.log.info(f"{self.scl_o_o} {self.sda_o_dly} {self.sda_o}")
#             
#             if self.scl_o_o and self.sda_o_dly and self.sda_o == 0:
#                 self.log.info("Start bit detected")
#                 self.log.info(self.scl_o_o.value)
#                 self.sda_i.value = 0;
# #                 
#                 for i in range(1):
#                     await self._half_bit_t
#                 self.sda_i.value = 1;
#                 await self._half_bit_t
#                 await self._half_bit_t
#                 self.sda_i.value = 0;
#             
#             self.sda_o_dly = int(self.sda_o.value)
#             #await self._half_bit_t

#     def _set_sda(self, val):
#         if self.sda_o is not None:
#             self.sda_o.value = val
#         else:
#             self.sda.value = val
#             # self.sda <= BinaryValue('z') if val else 0
# 
#     def _set_scl(self, val):
#         if self.scl_o_o is not None:
#             self.scl_o_o.value = val
#         else:
#             self.scl_o.value = val
#             # self.scl_o <= BinaryValue('z') if val else 0
# 
#     async def send_start(self):
#         if self.bus_active:
#             self._set_sda(1)
#             await self._half_bit_t
#             self._set_scl(1)
#             while not self.scl_o.value:
#                 await RisingEdge(self.scl_o)
#             await self._half_bit_t
# 
#         self._set_sda(0)
#         await self._half_bit_t
#         self._set_scl(0)
#         await self._half_bit_t
# 
#         self.bus_active = True
# 
#     async def send_stop(self):
#         if not self.bus_active:
#             return
# 
#         self._set_sda(0)
#         await self._half_bit_t
#         self._set_scl(1)
#         while not self.scl_o.value:
#             await RisingEdge(self.scl_o)
#         await self._half_bit_t
#         self._set_sda(1)
#         await self._half_bit_t
# 
#         self.bus_active = False
# 
#     async def send_bit(self, b):
#         if not self.bus_active:
#             self.send_start()
# 
#         self._set_sda(bool(b))
#         await self._half_bit_t
#         self._set_scl(1)
#         while not self.scl_o.value:
#             await RisingEdge(self.scl_o)
#         await self._bit_t
#         self._set_scl(0)
#         await self._half_bit_t
# 
#     async def recv_bit(self):
#         if not self.bus_active:
#             self.send_start()
# 
#         self._set_sda(1)
#         await self._half_bit_t
#         b = bool(self.sda.value.integer)
#         self._set_scl(1)
#         while not self.scl_o.value:
#             await RisingEdge(self.scl_o)
#         await self._bit_t
#         self._set_scl(0)
#         await self._half_bit_t
# 
#         return b
# 
#     async def send_byte(self, b):
#         for i in range(8):
#             await self.send_bit(b & (1 << 7-i))
#         return await self.recv_bit()
# 
#     async def recv_byte(self, ack):
#         b = 0
#         for i in range(8):
#             b = (b << 1) | await self.recv_bit()
#         await self.send_bit(ack)
#         return b
# 
#     async def write(self, addr, data):
#         self.log.info("Write %s to device at I2C address 0x%02x", data, addr)
#         await self.send_start()
#         ack = await self.send_byte((addr << 1) | 0)
#         if ack:
#             self.log.info("Got NACK")
#         for b in data:
#             ack = await self.send_byte(b)
#             if ack:
#                 self.log.info("Got NACK")
# 
#     async def read(self, addr, count):
#         self.log.info("Read %d bytes from device at I2C address 0x%02x", count, addr)
#         await self.send_start()
#         ack = await self.send_byte((addr << 1) | 1)
#         if ack:
#             self.log.info("Got NACK")
#         data = bytearray()
#         for k in range(count):
#             data.append(await self.recv_byte(k == count-1))
#         return data
