#pragma once

// dragonpilot: panda_tici 固件专用的 hyundai_canfd shadow，仅对 panda_tici 固件编译生效
// （靠 panda_tici/SConscript 的 include 顺序 shadow 掉主线 opendbc 同名文件），主机侧与主线 opendbc 不受影响。
//
// 背景：主线 opendbc 的 safety.h 无条件 include 本模式，而 hyundai_canfd 会访问 msg->data[16..18]。
// C3(F4/DOS/STM32F413) 性能受限、不跑 CANFD 车型，其 CANPacket_t.data 只有 8 字节（见 panda_tici/opendbc/safety/can.h），
// 若编译主线 hyundai_canfd 会数组越界（-Werror=array-bounds）。
//
// 复刻 DP 的 #ifdef CANFD 隔离逻辑：
//   - H7（定义 CANFD，64U）：转发到主线真身，功能完整。
//   - F4（未定义 CANFD，8U）：提供一个不访问 data[8+] 的 no-output stub，满足 safety.h 中
//     `{SAFETY_HYUNDAI_CANFD, &hyundai_canfd_hooks}` 的符号引用，且 F4 本就不会进入该 safety 模式。

#ifdef CANFD
  // H7：使用主线完整实现（继续沿 include 路径查找 opendbc_repo 中的同名文件）
  #include_next "opendbc/safety/modes/hyundai_canfd.h"
#else
  // F4：no-output stub，复用 defaults.h 中已定义的 hook（safety.h 在本文件之前已 include defaults.h）
  const safety_hooks hyundai_canfd_hooks = {
    .init = nooutput_init,
    .rx = default_rx_hook,
    .tx = nooutput_tx_hook,
  };
#endif
