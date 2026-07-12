#pragma once

// dragonpilot: panda_tici 固件专用的条件化 CANPacket_t 布局。
// 主线 opendbc/safety/can.h 已改为无条件 CANPACKET_DATA_SIZE_MAX=64U，
// 但 C3(F4/DOS) 的 STM32F413 只跑经典 CAN，需要 8U 布局（与固件 CAN_PACKET_VERSION=4 契约一致）。
// panda_tici/SConscript 的 include 顺序把 panda_tici 根目录排在 opendbc.INCLUDE_PATH 之前，
// 因此本文件只对 panda_tici 固件编译生效，主机侧 pandad 与主线 opendbc 不受影响。
// 逻辑完全复刻 DP：F4(未定义 CANFD)=8U，H7(定义 CANFD)=64U。

static const unsigned char dlc_to_len[] = {0U, 1U, 2U, 3U, 4U, 5U, 6U, 7U, 8U, 12U, 16U, 20U, 24U, 32U, 48U, 64U};

#define CANPACKET_HEAD_SIZE 6U  // non-data portion of CANPacket_t

#ifdef CANFD
  #define CANPACKET_DATA_SIZE_MAX 64U
#else
  #define CANPACKET_DATA_SIZE_MAX 8U
#endif

typedef struct {
  unsigned char fd : 1;
  unsigned char bus : 3;
  unsigned char data_len_code : 4;  // lookup length with dlc_to_len
  unsigned char rejected : 1;
  unsigned char returned : 1;
  unsigned char extended : 1;
  unsigned int addr : 29;
  unsigned char checksum;
  unsigned char data[CANPACKET_DATA_SIZE_MAX];
} __attribute__((packed, aligned(4))) CANPacket_t;

#define GET_LEN(msg) (dlc_to_len[(msg)->data_len_code])
