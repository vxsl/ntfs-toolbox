import time, os, copy
from shutil import disk_usage
from threading import Thread, Lock, current_thread
from concurrent import futures
from multiprocessing import cpu_count
from PyQt5 import QtCore
from .performance.performance import PerformanceCalc, ExpressPerformanceCalc

#0A30303032383439363733203030303030206E200A30303032383439333138203030303030206E200A30303032383439363531203030303030206E200A30303032383439393233203030303030206E200A30303032383537363833203030303030206E200A30303032383538323835203030303030206E200A30303032383537393135203030303030206E200A30303032383538323633203030303030206E200A30303032383538353434203030303030206E200A30303032383636363038203030303030206E200A747261696C65720A3C3C202F53697A652031303737202F526F6F742035323720302052202F496E666F203120302052202F4944205B203C31636634313034613362636233306164653433313866363835356238356334623E0A3C31636634313034613362636233306164653433313866363835356238356334623E205D203E3E0A7374617274787265660A323836363834310A2525454F460A0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000
TEST = b'\n0002849673 00000 n \n0002849318 00000 n \n0002849651 00000 n \n0002849923 00000 n \n0002857683 00000 n \n0002858285 00000 n \n0002857915 00000 n \n0002858263 00000 n \n0002858544 00000 n \n0002866608 00000 n \ntrailer\n<< /Size 1077 /Root 527 0 R /Info 1 0 R /ID [ <1cf4104a3bcb30ade4318f6855b85c4b>\n<1cf4104a3bcb30ade4318f6855b85c4b> ] >>\nstartxref\n2866841\n%%EOF\n\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

SECTOR_SIZE = 512 # bytes
MEANINGLESS_SECTORS = [b'\x00' * SECTOR_SIZE, b'\xff' * SECTOR_SIZE]
lock = Lock()
job = None
executor = futures.ThreadPoolExecutor(max_workers=(cpu_count()))
#addr == int('4191FFA5000', 16) and inp == sector
def check_sector(inp, addr, close_reader=None):
    for sector in job.source_file.remaining_sectors:
        if inp == sector and ((addr - SECTOR_SIZE), sector) not in job.rebuilt_file:
            hex_addr = hex(addr - SECTOR_SIZE)
            with lock:
                i = job.source_file.get_unique_sector_index(sector)
                job.rebuilt_file[i] = ((addr - SECTOR_SIZE), copy.deepcopy(sector))
                job.source_file.remaining_sectors.remove(sector)
            job.success_update.emit(i)
            if close_reader:
                close_reader.success_count += 1
            elif not job.primary_reader.inspection_in_progress(addr):
                close_inspect(addr - SECTOR_SIZE)
            print("check_sector: sector at logical address " + hex_addr + " on disk is equal to sector " + str(i) + " of source file.")            
            job.log.write(hex_addr + "\t\t" + str(i) + "\n")
            job.log.flush()
            
            if not filter(None, job.source_file.remaining_sectors):
                job.finished.emit(None)
            return
    return

def close_inspect(addr):
    forward = ForwardCloseReader()
    backward = BackwardCloseReader()
    job.primary_reader.inspections.append((hex(addr), forward))
    job.primary_reader.inspections.append((hex(addr), backward))
    #Thread(name='close inspect forward @' + addr,target=forward.read,args=[addr]).start()
    #Thread(name='close inspect backward @' + addr,target=backward.read,args=[addr]).start()
    executor.submit(forward.read, addr)
    executor.submit(backward.read, addr)


class DiskReader(QtCore.QObject):
    def __init__(self, disk_path):
        super().__init__()
        self.fd = os.fdopen(os.open(disk_path, os.O_RDONLY | os.O_BINARY), 'rb')

class CloseReader(DiskReader):
    def __init__(self):
        super().__init__(job.disk_path)
        self.sector_limit = (job.total_sectors * 6) #???
        self.sector_count = 0
        self.success_count = 0

class ForwardCloseReader(CloseReader):
    def read(self, addr):
        current_thread().name = ("Forward close reader at " + hex(addr))
        self.fd.seek(addr)
        for _ in range(self.sector_limit):
            #check_sector(self.fd.read(SECTOR_SIZE), self.fd.tell(), True)
            data = self.fd.read(SECTOR_SIZE)
            if data not in MEANINGLESS_SECTORS or self.success_count > (self.sector_count / 2):
                executor.submit(check_sector, data, self.fd.tell(), self)
        with lock:
            job.primary_reader.inspections.remove((hex(addr), self))
        current_thread().name = ("Control returned from a forward close reader at " + hex(addr))
        return

class BackwardCloseReader(CloseReader):
    def read(self, addr):
        current_thread().name = ("Backward close reader at " + hex(addr))
        self.fd.seek(addr)
        for _ in range(self.sector_limit):
            #check_sector(self.fd.read(SECTOR_SIZE), self.fd.tell(), True)
            executor.submit(check_sector, self.fd.read(SECTOR_SIZE), self.fd.tell(), self)
            self.fd.seek(-1024, 1)
        with lock:
            job.primary_reader.inspections.remove((hex(addr), self))
        current_thread().name = ("Control returned from a backward close reader at " + hex(addr))
        return

class PrimaryReader(DiskReader):

    def read(self, addr):
        self.fd.seek(addr)
        #executor = futures.ThreadPoolExecutor(thread_name_prefix="Primary Reader Pool", max_workers=(cpu_count()))
        while True:
            executor.submit(check_sector, self.fd.read(SECTOR_SIZE), self.fd.tell())
            executor.submit(job.perf.increment())


class ExpressPrimaryReader(PrimaryReader):

    def __init__(self, disk_path, total_sectors):
        super().__init__(disk_path)
        self.jump_size = total_sectors//2 * SECTOR_SIZE
        self.inspections = []

    def read(self, addr):
        self.fd.seek(addr)
        #executor = futures.ThreadPoolExecutor(thread_name_prefix="Express Primary Reader Pool", max_workers=(cpu_count()))

        for _ in range(job.diskSize.total - addr):
            data = self.fd.read(SECTOR_SIZE)
            if not data:
                break
            if data in MEANINGLESS_SECTORS:
                continue
            executor.submit(check_sector, data, self.fd.tell())
            executor.submit(job.perf.increment)
            self.fd.seek(self.jump_size, 1)

        job.finished.emit(None)

    def inspection_in_progress(self, addr):
        for address, reader in self.inspections:
            upper_limit = int(address, 16) + (reader.sector_limit * SECTOR_SIZE)
            lower_limit = int(address, 16) - (reader.sector_limit * SECTOR_SIZE)
            if lower_limit <= addr and addr <= upper_limit:
                return True
        return False
    
class Job(QtCore.QObject):

    # PyQt event signaller
    success_update = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal(object)

    def build_file(self):
        out_file = open(self.dir_name + '/' + job.reference_file.name.split('.')[0] + "_RECONSTRUCTED_" + job.reference_file.name.split('.')[1], 'wb')
        for sector in self.rebuilt_file:
            out_file.write(sector)
        out_file.close() 

    def __init__(self, vol, source_file, do_logging, express):
        super().__init__()
        self.express = express
        self.disk_path = r"\\." + "\\" + vol + ":"
        self.diskSize = disk_usage(vol + ':\\')
        self.source_file = source_file
        self.done_sectors = 0
        self.total_sectors = len(source_file.sectors)
        self.rebuilt_file = [None] * self.total_sectors
        self.finished.connect(self.build_file)

        if express == True:
            self.primary_reader = ExpressPrimaryReader(self.disk_path, self.total_sectors)
            self.perf = ExpressPerformanceCalc(self.total_sectors)
        else:
            job.primary_reader = PrimaryReader(self.disk_path)
            job.perf = PerformanceCalc()

        if do_logging == True:
            self.dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(self.dir_name, mode=0o755)
            self.log = open(self.dir_name + '/' + self.source_file.name + ".log", 'w')
        else:
            self.dir_name = 'ntfs-toolbox/' + 'recreate_file ' + time.ctime().replace(":", '_')
            os.makedirs(self.dir_name, mode=0o755)
            self.log = open(self.dir_name + '/' + self.source_file.name + ".log", 'w')
            # do something...
            print("Undefined behaviour")



class SourceFile():
    def __init__(self, path):
        self.sectors = self.to_sectors(path)
        self.remaining_sectors = copy.deepcopy(self.sectors)
        split = path.split('/')
        self.dir = '/'.join(split[0:(len(split) - 1)])
        self.name = split[len(split) - 1]

    def get_unique_sector_index(self, sector):

        occurrences = [i for i, s in enumerate(self.sectors) if s == sector] # get all occurences of this data
        if len(occurrences) > 1:
            for index in occurrences:
                if job.rebuilt_file[index] == None:
                    return index
        else:
            return occurrences[0]


    def to_sectors(self, path):
        file = open(path, "rb")
        file.seek(0)
        result = []
        while True:
            cur = file.read(SECTOR_SIZE)
            if cur == b'':
                break
            elif len(cur) == SECTOR_SIZE:
                result.append(cur)
            else:
                result.append((bytes.fromhex((cur.hex()[::-1].zfill(1024)[::-1])), False))   #trailing sector zfill
        return result

def initialize_job(do_logging, express, selected_vol, source_file):
    global job
    job = Job(selected_vol, source_file, do_logging, express)
    return job

