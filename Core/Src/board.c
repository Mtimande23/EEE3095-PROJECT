/*
 * board.c - Clock, GPIO, UART, SysTick and LCD set-up by direct register access.
 *
 * The UART receive interrupt only moves bytes into a ring buffer; all
 * parsing happens in the main loop.
 */
#include "board.h"

#define RX_RING_SIZE   64u        /* power of two */
#define TX_SPIN_LIMIT  100000u    /* many byte times even at 48 MHz */

static volatile uint32_t ms_ticks;
static uint32_t clock_hz = BOARD_HSI_HZ;

static volatile uint8_t  rx_ring[RX_RING_SIZE];
static volatile uint16_t rx_head;   /* written by the ISR       */
static volatile uint16_t rx_tail;   /* written by the main loop */
static volatile uint8_t  rx_error;

/*
 * Some startup files call SystemInit() before main(). The chip already runs
 * from the 8 MHz HSI after reset, which is all we need, so provide an empty
 * one. It is weak, so a real system_stm32f0xx.c in the project wins.
 */
__attribute__((weak)) void SystemInit(void)
{
}

/* ----------------------------------------------------------- interrupts -- */

void SysTick_Handler(void)
{
    ms_ticks++;
}

static void uart_irq(void)
{
    uint32_t isr = USART_ISR(UART_BASE);

    if (isr & USART_ICR_ERRORS) {
        /* Overrun, framing, noise or parity: clear the flags, or the
           interrupt fires forever, and mark the frame as damaged. */
        USART_ICR(UART_BASE) = USART_ICR_ERRORS;
        rx_error = 1;
    }
    if (isr & USART_ISR_RXNE) {
        uint8_t  b    = (uint8_t)USART_RDR(UART_BASE);   /* clears RXNE */
        uint16_t next = (uint16_t)((rx_head + 1u) & (RX_RING_SIZE - 1u));
        if (next == rx_tail) {
            rx_error = 1;                                 /* ring full */
        } else {
            rx_ring[rx_head] = b;
            rx_head = next;
        }
    }
}

#if GAME_UART == 1
void USART1_IRQHandler(void) { uart_irq(); }
#else
void USART2_IRQHandler(void) { uart_irq(); }
#endif

/* ---------------------------------------------------------------- setup -- */

static void gpio_mode(uint32_t port, uint32_t pin, uint32_t mode)
{
    uint32_t m = GPIO_MODER(port);
    m &= ~(3u << (pin * 2u));
    m |= (mode << (pin * 2u));
    GPIO_MODER(port) = m;
}

static void gpio_af(uint32_t port, uint32_t pin, uint32_t af)
{
    if (pin < 8u) {
        GPIO_AFRL(port) = (GPIO_AFRL(port) & ~(0xFu << (pin * 4u))) | (af << (pin * 4u));
    } else {
        pin -= 8u;
        GPIO_AFRH(port) = (GPIO_AFRH(port) & ~(0xFu << (pin * 4u))) | (af << (pin * 4u));
    }
}

/*
 * Switch SYSCLK from the 8 MHz HSI to the PLL at 48 MHz (HSI/2 x 12).
 * At 8 MHz the nearest UART divider gives 115942 baud (+0.64%); at 48 MHz it
 * gives 115108 baud (-0.08%), which leaves far more margin for the HSI's own
 * +/-1% tolerance. Every wait is bounded; on failure we stay on the HSI.
 */
static void clock_init(void)
{
    uint32_t spins;

    FLASH_ACR = FLASH_ACR_PRFTBE | FLASH_ACR_LATENCY;

    /* If a SystemInit already runs us from the PLL, step back to the HSI
       first: the PLL cannot be stopped or reprogrammed while it is SYSCLK. */
    RCC_CFGR &= ~RCC_CFGR_SW_MASK;
    for (spins = 0; (RCC_CFGR & RCC_CFGR_SWS_MASK) != 0u && spins < 100000u; spins++) { }

    RCC_CR &= ~RCC_CR_PLLON;
    for (spins = 0; (RCC_CR & RCC_CR_PLLRDY) && spins < 100000u; spins++) { }
    RCC_CFGR = (RCC_CFGR & ~(RCC_CFGR_PLLMUL_MASK | RCC_CFGR_PLLSRC)) | RCC_CFGR_PLLMUL12;
    RCC_CR |= RCC_CR_PLLON;
    for (spins = 0; !(RCC_CR & RCC_CR_PLLRDY); spins++) {
        if (spins > 100000u)
            return;                          /* PLL never locked: keep HSI */
    }

    RCC_CFGR = (RCC_CFGR & ~RCC_CFGR_SW_MASK) | RCC_CFGR_SW_PLL;
    for (spins = 0; (RCC_CFGR & RCC_CFGR_SWS_MASK) != RCC_CFGR_SWS_PLL; spins++) {
        if (spins > 100000u)
            return;
    }
    clock_hz = BOARD_PLL_HZ;
}

void board_init(void)
{
    clock_init();

    /* Clocks for GPIOA, GPIOB, GPIOC (LCD) and the UART. */
    RCC_AHBENR |= RCC_AHBENR_IOPAEN | RCC_AHBENR_IOPBEN | RCC_AHBENR_IOPCEN;
#if GAME_UART == 1
    RCC_APB2ENR |= RCC_APB2ENR_USART1EN;
#else
    RCC_APB1ENR |= RCC_APB1ENR_USART2EN;
#endif

    /* Button: input (00) with pull-up (01). */
    gpio_mode(BTN_PORT_BASE, BTN_PIN, 0u);
    GPIO_PUPDR(BTN_PORT_BASE) = (GPIO_PUPDR(BTN_PORT_BASE) & ~(3u << (BTN_PIN * 2u)))
                              | (1u << (BTN_PIN * 2u));

    /* LED: output (01), start off. */
    gpio_mode(LED_PORT_BASE, LED_PIN, 1u);
    board_led(0);

    /* UART pins: alternate function (10), AF1 = USART on these pins. */
#if GAME_UART == 1
    gpio_mode(GPIOA_BASE, 9u, 2u);
    gpio_mode(GPIOA_BASE, 10u, 2u);
    gpio_af(GPIOA_BASE, 9u, 1u);
    gpio_af(GPIOA_BASE, 10u, 1u);
#else
    gpio_mode(GPIOA_BASE, 2u, 2u);
    gpio_mode(GPIOA_BASE, 3u, 2u);
    gpio_af(GPIOA_BASE, 2u, 1u);
    gpio_af(GPIOA_BASE, 3u, 1u);
#endif

    /* UART: 115200 8N1 from the system clock (48 MHz: BRR = 417 -> 115108
       baud, -0.08%), receive interrupt on. */
    USART_CR1(UART_BASE) = 0;
    USART_BRR(UART_BASE) = (clock_hz + BOARD_BAUD / 2u) / BOARD_BAUD;
    USART_CR1(UART_BASE) = USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE | USART_CR1_UE;
    NVIC_ISER = (1u << UART_IRQn);

    /* SysTick: 1 ms tick from the processor clock. */
    SYST_RVR = clock_hz / 1000u - 1u;
    SYST_CVR = 0;
    SYST_CSR = 7u;   /* CLKSOURCE | TICKINT | ENABLE */
}

/* ------------------------------------------------------------------ API -- */

uint32_t board_millis(void)
{
    return ms_ticks;
}

uint32_t board_clock_hz(void)
{
    return clock_hz;
}

int board_uart_getc(uint8_t *out)
{
    if (rx_tail == rx_head)
        return 0;
    *out = rx_ring[rx_tail];
    rx_tail = (uint16_t)((rx_tail + 1u) & (RX_RING_SIZE - 1u));
    return 1;
}

int board_uart_take_error(void)
{
    if (!rx_error)
        return 0;
    rx_error = 0;
    return 1;
}

void board_uart_puts(const char *s)
{
    while (*s) {
        uint32_t spins = 0;
        while (!(USART_ISR(UART_BASE) & USART_ISR_TXE)) {
            if (++spins > TX_SPIN_LIMIT)
                return;          /* UART stuck: drop the reply, never hang */
        }
        USART_TDR(UART_BASE) = (uint8_t)*s++;
    }
}

int board_button_down(void)
{
    return (GPIO_IDR(BTN_PORT_BASE) & (1u << BTN_PIN)) == 0;
}

void board_led(int on)
{
    GPIO_BSRR(LED_PORT_BASE) = on ? (1u << LED_PIN) : (1u << (LED_PIN + 16u));
}

/* ------------------------------------------------------------------ LCD -- */

static void delay_ms(uint32_t ms)
{
    uint32_t start = board_millis();
    while (board_millis() - start <= ms) { }    /* at least ms whole ticks */
}

static void pin_write(uint32_t port, uint32_t pin, int high)
{
    GPIO_BSRR(port) = high ? (1u << pin) : (1u << (pin + 16u));
}

/* Put 4 bits on D4..D7 and pulse E; the LCD latches on the falling edge. */
static void lcd_nibble(uint8_t n)
{
    pin_write(LCD_D4_PORT, LCD_D4_PIN, n & 1u);
    pin_write(LCD_D5_PORT, LCD_D5_PIN, n & 2u);
    pin_write(LCD_D6_PORT, LCD_D6_PIN, n & 4u);
    pin_write(LCD_D7_PORT, LCD_D7_PIN, n & 8u);
    pin_write(LCD_E_PORT, LCD_E_PIN, 1);
    for (volatile int i = 0; i < 50; i++) { }   /* E high >= 450 ns */
    pin_write(LCD_E_PORT, LCD_E_PIN, 0);
}

/* RW is tied to GND, so the busy flag cannot be read: wait instead. */
static void lcd_command(uint8_t cmd)
{
    pin_write(LCD_RS_PORT, LCD_RS_PIN, 0);
    lcd_nibble(cmd >> 4);
    lcd_nibble(cmd & 0xFu);
    delay_ms(2);                                 /* clear needs 1.52 ms */
}

void board_lcd_clear(void)
{
    gpio_mode(LCD_RS_PORT, LCD_RS_PIN, 1u);
    gpio_mode(LCD_E_PORT, LCD_E_PIN, 1u);
    gpio_mode(LCD_D4_PORT, LCD_D4_PIN, 1u);
    gpio_mode(LCD_D5_PORT, LCD_D5_PIN, 1u);
    gpio_mode(LCD_D6_PORT, LCD_D6_PIN, 1u);
    gpio_mode(LCD_D7_PORT, LCD_D7_PIN, 1u);
    pin_write(LCD_E_PORT, LCD_E_PIN, 0);
    pin_write(LCD_RS_PORT, LCD_RS_PIN, 0);

    /* Reset by instruction (HD44780 datasheet, fig. 24). This works whatever
       state the previous program left the LCD in, even halfway through a
       4-bit byte. */
    delay_ms(50);
    lcd_nibble(0x3u);
    delay_ms(5);
    lcd_nibble(0x3u);
    delay_ms(1);
    lcd_nibble(0x3u);
    delay_ms(1);
    lcd_nibble(0x2u);                            /* now in 4-bit mode */
    delay_ms(1);

    lcd_command(0x28u);    /* 4-bit, 2 lines, 5x8 font  */
    lcd_command(0x08u);    /* display off               */
    lcd_command(0x01u);    /* clear, cursor home        */
    lcd_command(0x06u);    /* move right, no shift      */
    lcd_command(0x0Cu);    /* display on, cursor off    */
}
