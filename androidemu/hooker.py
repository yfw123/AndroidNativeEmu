from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from unicorn import *
from unicorn.arm_const import UC_ARM_REG_R4


# Utility class to create a bridge between ARM and Python.
class Hooker:

    """
    :type mu Uc
    """
    def __init__(self, mu, base_addr):
        self._mu = mu
        self._keystone = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
        self._base_addr = base_addr
        self._current_id = 0xFF00
        self._current_addr = self._base_addr
        self._hooks = dict()

    def _get_next_id(self):
        idx = self._current_id
        self._current_id += 1
        return idx

    def write_function(self, func):
        # Get the hook id.
        hook_id = self._get_next_id()
        hook_addr = self._current_addr

        # Create the ARM assembly code.
        asm = "PUSH {R4,LR}\n" \
              "MOV R4, #" + hex(hook_id) + "\n" \
              "IT AL\n" \
              "POP {R4,PC}"

        asm_bytes_list, asm_count = self._keystone.asm(bytes(asm, encoding='ascii'))

        if asm_count != 4:
            raise ValueError("Expected asm_count to be 4.")

        # Write assembly code to the emulator.
        self._mu.mem_write(hook_addr, bytes(asm_bytes_list))

        # Save results.
        self._current_addr += len(asm_bytes_list)
        self._hooks[hook_id] = func

        return hook_addr

    def write_function_table(self, table):
        if not isinstance(table, dict):
            raise ValueError("Expected a dictionary for the function table.")

        index_max = int(max(table, key=int)) + 1

        # First, we write every function and store its result address.
        hook_map = dict()

        for index, func in table.items():
            hook_map[index] = self.write_function(func)

        # Then we write the function table.
        table_bytes = b""
        table_address = self._current_addr

        for index in range(0, index_max):
            address = hook_map[index] if index in hook_map else 0
            table_bytes += int(address + 1).to_bytes(4, byteorder='little')  # + 1 because THUMB.

        self._mu.mem_write(table_address, table_bytes)
        self._current_addr += len(table_bytes)

        # Then we write the a pointer to the table.
        ptr_address = self._current_addr
        self._mu.mem_write(ptr_address, table_address.to_bytes(4, byteorder='little'))
        self._current_addr += 4

        return ptr_address, table_address

    def _hook(self, mu, address, size, user_data):
        # Check if instruction is "IT AL"
        if size != 2 or self._mu.mem_read(address, size) != b"\xE8\xBF":
            return

        # Find hook.
        hook_id = self._mu.reg_read(UC_ARM_REG_R4)
        hook_func = self._hooks[hook_id]

        # Call hook.
        hook_func(mu)

    def enable(self):
        self._mu.hook_add(UC_HOOK_CODE, self._hook, None, self._base_addr, self._current_addr)