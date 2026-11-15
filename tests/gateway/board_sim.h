#ifndef BOARD_SIM_H
#define BOARD_SIM_H
#ifdef __cplusplus
extern "C" {
#endif
void sim_start(const char *mode);
void sim_erase_all(void);
void sim_feed(unsigned char value);
int sim_read(void);
int sim_in_app(void);
int sim_app_valid(void);
unsigned long sim_hole_writes(void);
unsigned char sim_flash_at(unsigned long offset);
#ifdef __cplusplus
}
#endif
#endif
