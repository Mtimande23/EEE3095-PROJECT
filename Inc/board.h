/*
 * board.h - Direct register access for the UCT STM32F051C8 board.
 *
 * No HAL, no CubeMX and no CMSIS headers: every register used is defined
 * here from the reference manual (RM0091), so the firmware builds in any
 * empty STM32F051C8 project.
 *
 * Pin choices (change here if your board differs):
 *   GAME_UART 1: USART1, PA9 = TX, PA10 = RX   (default)
 *   GAME_UART 2: USART2, PA2 = TX, PA3  = RX
 *   Button: PA0, pressed = low (internal pull-up enabled)
 *   LED:    PB0, high = on
 */
#ifndef BOARD_H
#define BOARD_H

#include <stdint.h>

#ifndef GAME_UART
#define GAME_UART 1
#endif

#define BOARD_HSI_HZ   8000000u   /* reset clock: internal 8 MHz HSI */
#define BOARD_BAUD     115200u

#define BTN_PORT_BASE  GPIOA_BASE
#define BTN_PIN        0u
#define LED_PORT_BASE  GPIOB_BASE
#define LED_PIN        0u

/* ------------------------------------------------- register map (RM0091) -- */

#define REG32(addr)      (*(volatile uint32_t *)(addr))

#define RCC_BASE         0x40021000u
#define RCC_AHBENR       REG32(RCC_BASE + 0x14u)
#define RCC_APB2ENR      REG32(RCC_BASE + 0x18u)
#define RCC_APB1ENR      REG32(RCC_BASE + 0x1Cu)
#define RCC_AHBENR_IOPAEN    (1u << 17)
#define RCC_AHBENR_IOPBEN    (1u << 18)
#define RCC_APB2ENR_USART1EN (1u << 14)
#define RCC_APB1ENR_USART2EN (1u << 17)

#define GPIOA_BASE       0x48000000u
#define GPIOB_BASE       0x48000400u
#define GPIO_MODER(p)    REG32((p) + 0x00u)
#define GPIO_PUPDR(p)    REG32((p) + 0x0Cu)
#define GPIO_IDR(p)      REG32((p) + 0x10u)
#define GPIO_BSRR(p)     REG32((p) + 0x18u)
#define GPIO_AFRL(p)     REG32((p) + 0x20u)
#define GPIO_AFRH(p)     REG32((p) + 0x24u)

#define USART1_BASE      0x40013800u
#define USART2_BASE      0x40004400u
#define USART_CR1(u)     REG32((u) + 0x00u)
#define USART_BRR(u)     REG32((u) + 0x0Cu)
#define USART_ISR(u)     REG32((u) + 0x1Cu)
#define USART_ICR(u)     REG32((u) + 0x20u)
#define USART_RDR(u)     REG32((u) + 0x24u)
#define USART_TDR(u)     REG32((u) + 0x28u)
#define USART_CR1_UE     (1u << 0)
#define USART_CR1_RE     (1u << 2)
#define USART_CR1_TE     (1u << 3)
#define USART_CR1_RXNEIE (1u << 5)
#define USART_ISR_PE     (1u << 0)
#define USART_ISR_FE     (1u << 1)
#define USART_ISR_NE     (1u << 2)
#define USART_ISR_ORE    (1u << 3)
#define USART_ISR_RXNE   (1u << 5)
#define USART_ISR_TXE    (1u << 7)
#define USART_ICR_ERRORS (USART_ISR_PE | USART_ISR_FE | USART_ISR_NE | USART_ISR_ORE)

#define USART1_IRQn      27u
#define USART2_IRQn      28u

#define SYST_CSR         REG32(0xE000E010u)
#define SYST_RVR         REG32(0xE000E014u)
#define SYST_CVR         REG32(0xE000E018u)
#define NVIC_ISER        REG32(0xE000E100u)

#if GAME_UART == 1
#define UART_BASE        USART1_BASE
#define UART_IRQn        USART1_IRQn
#elif GAME_UART == 2
#define UART_BASE        USART2_BASE
#define UART_IRQn        USART2_IRQn
#else
#error "GAME_UART must be 1 or 2"
#endif

/* ------------------------------------------------------------------- API -- */

void     board_init(void);
uint32_t board_millis(void);

/* Pop one received byte. Returns 1 if a byte was available. */
int      board_uart_getc(uint8_t *out);
/* Returns 1 (once) if bytes were lost to overrun, noise or a full buffer. */
int      board_uart_take_error(void);
/* Send a string. Bounded wait per byte, so it can never hang. */
void     board_uart_puts(const char *s);

int      board_button_down(void);   /* raw level, 1 = pressed */
void     board_led(int on);

#endif /* BOARD_H */
