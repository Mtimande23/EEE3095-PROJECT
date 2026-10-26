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
 *   LCD:    16x2 HD44780 in 4-bit mode, RW tied to GND:
 *           RS = PC14, E = PC15, D4 = PB8, D5 = PB9, D6 = PA12, D7 = PA15
 */
#ifndef BOARD_H
#define BOARD_H

#include <stdint.h>

#ifndef GAME_UART
#define GAME_UART 1
#endif

#define BOARD_HSI_HZ   8000000u   /* reset clock: internal 8 MHz HSI          */
#define BOARD_PLL_HZ   48000000u  /* HSI/2 x 12: the clock board_init sets up */
#define BOARD_BAUD     115200u

#define BTN_PORT_BASE  GPIOA_BASE
#define BTN_PIN        0u
#define LED_PORT_BASE  GPIOB_BASE
#define LED_PIN        0u

#define LCD_RS_PORT    GPIOC_BASE
#define LCD_RS_PIN     14u
#define LCD_E_PORT     GPIOC_BASE
#define LCD_E_PIN      15u
#define LCD_D4_PORT    GPIOB_BASE
#define LCD_D4_PIN     8u
#define LCD_D5_PORT    GPIOB_BASE
#define LCD_D5_PIN     9u
#define LCD_D6_PORT    GPIOA_BASE
#define LCD_D6_PIN     12u
#define LCD_D7_PORT    GPIOA_BASE
#define LCD_D7_PIN     15u

/* ------------------------------------------------- register map (RM0091) -- */

#define REG32(addr)      (*(volatile uint32_t *)(addr))

#define RCC_BASE         0x40021000u
#define RCC_CR           REG32(RCC_BASE + 0x00u)
#define RCC_CFGR         REG32(RCC_BASE + 0x04u)
#define RCC_CR_PLLON     (1u << 24)
#define RCC_CR_PLLRDY    (1u << 25)
#define RCC_CFGR_SW_MASK (3u << 0)
#define RCC_CFGR_SW_PLL  (2u << 0)
#define RCC_CFGR_SWS_MASK (3u << 2)
#define RCC_CFGR_SWS_PLL (2u << 2)
#define RCC_CFGR_PLLSRC  (1u << 16)    /* 0 = HSI/2 */
#define RCC_CFGR_PLLMUL_MASK (0xFu << 18)
#define RCC_CFGR_PLLMUL12    (0xAu << 18)

#define FLASH_ACR        REG32(0x40022000u)
#define FLASH_ACR_LATENCY (1u << 0)    /* 1 wait state, needed above 24 MHz */
#define FLASH_ACR_PRFTBE (1u << 4)
#define RCC_AHBENR       REG32(RCC_BASE + 0x14u)
#define RCC_APB2ENR      REG32(RCC_BASE + 0x18u)
#define RCC_APB1ENR      REG32(RCC_BASE + 0x1Cu)
#define RCC_AHBENR_IOPAEN    (1u << 17)
#define RCC_AHBENR_IOPBEN    (1u << 18)
#define RCC_AHBENR_IOPCEN    (1u << 19)
#define RCC_APB2ENR_USART1EN (1u << 14)
#define RCC_APB1ENR_USART2EN (1u << 17)

#define GPIOA_BASE       0x48000000u
#define GPIOB_BASE       0x48000400u
#define GPIOC_BASE       0x48000800u
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
uint32_t board_clock_hz(void);      /* 48 MHz, or 8 MHz if the PLL failed */

/* Pop one received byte. Returns 1 if a byte was available. */
int      board_uart_getc(uint8_t *out);
/* Returns 1 (once) if bytes were lost to overrun, noise or a full buffer. */
int      board_uart_take_error(void);
/* Send a string. Bounded wait per byte, so it can never hang. */
void     board_uart_puts(const char *s);

int      board_button_down(void);   /* raw level, 1 = pressed */
void     board_led(int on);

/* Set up the LCD and clear whatever an earlier program left on it.
   Call after board_init (it needs SysTick); takes about 60 ms. */
void     board_lcd_clear(void);

#endif /* BOARD_H */
