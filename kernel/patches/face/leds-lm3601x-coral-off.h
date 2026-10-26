/* SPDX-License-Identifier: GPL-2.0-only */
/* Coral identity/OFF diagnostic. This path never registers an LED interface.
 * Stock reference: Google msm 6ef255005cea, lm36011_module.c:713-838.
 * Retail lock, optical pulse and duty decoding remain UNVERIFIED.
 */
#include <linux/gpio/consumer.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>

struct coral_off_probe {
	struct regulator_bulk_data supply[4];
	u8 id[2], enable[2], flags[2], map[28], fault_flag;
	u8 raised, disabled, released, off_verified, id_read, flags_read, voltage_read;
	int error, fault_gpio, rail_uv[4], map_read;
	const char *stage;
	bool verified, f7_read;
};

/* Exact PVT/ver4 comparison set, Google lm36011_module.c:230-237. */
static const u8 coral_silego_registers[] = {
	0xc0, 0xc1, 0xc2, 0xc3, 0xcb, 0xcc, 0xce, 0x92, 0x93, 0xa0,
	0xa2, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88,
	0x89, 0x8a, 0x8b, 0x8c, 0x8d, 0x8e, 0x8f, 0x90,
};
static const u8 coral_silego_values[] = {
	0x01, 0xa6, 0xe0, 0xa6, 0x97, 0x9a, 0x9b, 0x00, 0x00, 0x1a,
	0x1a, 0xb0, 0x24, 0x58, 0x2c, 0x60, 0x2c, 0x40, 0x40, 0x3e,
	0x60, 0x00, 0x30, 0x7c, 0x24, 0xa0, 0x80, 0x00,
};
static DEFINE_MUTEX(coral_off_mutex);

static bool lm3601x_coral_off_mode(struct i2c_client *client)
{
	return of_device_is_compatible(client->dev.of_node,
				      "google,coral-lm36011-off-probe");
}

/* No regmap defaults/cache: every value is a physical I2C read. */
static int coral_off_read(struct i2c_client *client, u8 reg, u8 *value)
{
	struct i2c_msg messages[] = {
		{ .addr = client->addr, .len = 1, .buf = &reg },
		{ .addr = client->addr, .flags = I2C_M_RD, .len = 1, .buf = value },
	};
	int ret = i2c_transfer(client->adapter, messages, ARRAY_SIZE(messages));

	return ret == ARRAY_SIZE(messages) ? 0 : (ret < 0 ? ret : -EIO);
}

/* The ONLY configuration write in the diagnostic is LM36011 ENABLE=0. */
static int coral_off_disable(struct i2c_client *client, u8 *readback)
{
	u8 bytes[] = { LM3601X_ENABLE_REG, 0 };
	int ret = i2c_master_send(client, bytes, sizeof(bytes));

	if (ret != sizeof(bytes))
		return ret < 0 ? ret : -EIO;
	ret = coral_off_read(client, LM3601X_ENABLE_REG, readback);
	return ret ?: (*readback ? -EIO : 0);
}

static struct i2c_client *coral_off_peer(struct device *dev, const char *name)
{
	struct device_node *node = of_parse_phandle(dev->of_node, name, 0);
	struct i2c_client *client;

	if (!node)
		return ERR_PTR(-EINVAL);
	client = of_find_i2c_device_by_node(node);
	of_node_put(node);
	return client ?: ERR_PTR(-EPROBE_DEFER);
}

static ssize_t coral_off_result_show(struct device *dev,
				    struct device_attribute *attr, char *buf)
{
	struct coral_off_probe *p = dev_get_drvdata(dev);

	return sysfs_emit(buf, "verified_off=%u error=%d id=%02x,%02x enable=%02x,%02x flags=%02x,%02x f7=%02x fault_gpio=%d stage=%s raised=%02x disabled=%02x released=%02x off_verified=%02x id_read=%02x flags_read=%02x map_read=%d f7_read=%u voltage_read=%02x rail_uv=%d,%d,%d,%d write_lock=unverified pulse_us=unknown duty=unknown on_inhibited=1\n",
		p->verified, p->error, p->id[0], p->id[1], p->enable[0], p->enable[1],
		p->flags[0], p->flags[1], p->fault_flag, p->fault_gpio, p->stage,
		p->raised, p->disabled, p->released, p->off_verified, p->id_read,
		p->flags_read, p->map_read, p->f7_read, p->voltage_read,
		p->rail_uv[0], p->rail_uv[1], p->rail_uv[2], p->rail_uv[3]);
}
static DEVICE_ATTR_RO(coral_off_result);

static ssize_t coral_silego_map_show(struct device *dev,
				   struct device_attribute *attr, char *buf)
{
	struct coral_off_probe *p = dev_get_drvdata(dev);
	int i, count = 0;

	for (i = 0; i < ARRAY_SIZE(coral_silego_registers); i++) {
		if (i < p->map_read)
			count += sysfs_emit_at(buf, count, "%02x=%02x\n",
				coral_silego_registers[i], p->map[i]);
		else
			count += sysfs_emit_at(buf, count, "%02x=unread\n",
				coral_silego_registers[i]);
	}
	return count;
}
static DEVICE_ATTR_RO(coral_silego_map);

static int lm3601x_coral_off_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	const char * const names[] = { "buck1", "buck2", "vio", "silego" };
	struct regulator_bulk_data *supply;
	const int voltage[] = { 1350000, 3300000, 1800000, 3200000 };
	struct i2c_client *emitters[] = { client, NULL }, *silego;
	struct coral_off_probe *p;
	struct gpio_desc *fault;
	int ret, cleanup, i, enabled = 0, voted = 0;

	if (!of_machine_is_compatible("google,coral") || client->addr != 0x64)
		return -EINVAL;
	emitters[1] = coral_off_peer(dev, "google,peer-emitter");
	if (IS_ERR(emitters[1]))
		return PTR_ERR(emitters[1]);
	silego = coral_off_peer(dev, "google,safety-controller");
	if (IS_ERR(silego)) {
		ret = PTR_ERR(silego);
		goto put_peer;
	}
	ret = -EINVAL;
	if (emitters[1]->addr != 0x64 || silego->addr != 0x08 ||
	    emitters[1]->adapter == client->adapter ||
	    silego->adapter != client->adapter)
		goto put_silego;
	p = devm_kzalloc(dev, sizeof(*p), GFP_KERNEL);
	if (!p) {
		ret = -ENOMEM;
		goto put_silego;
	}
	p->fault_gpio = -ENODATA;
	p->stage = "not-started";
	fault = devm_gpiod_get(dev, "fault", GPIOD_IN);
	if (IS_ERR(fault)) {
		ret = PTR_ERR(fault);
		goto put_silego;
	}
	supply = p->supply;
	for (i = 0; i < ARRAY_SIZE(p->supply); i++)
		supply[i].supply = names[i];
	ret = devm_regulator_bulk_get(dev, ARRAY_SIZE(p->supply), supply);
	if (ret)
		goto put_silego;
	i2c_set_clientdata(client, p);
	/* Publish storage before power: no allocation failure can discard a
	 * retained safety vote after a hardware cleanup error.
	 */
	p->error = -EINPROGRESS;
	ret = device_create_file(dev, &dev_attr_coral_off_result);
	if (ret)
		goto put_silego;
	ret = device_create_file(dev, &dev_attr_coral_silego_map);
	if (ret) {
		device_remove_file(dev, &dev_attr_coral_off_result);
		goto put_silego;
	}
	mutex_lock(&coral_off_mutex);
	/* Exact stock order; incompatible rear 2.8V votes reject 3.2V. */
	p->stage = "rails";
	for (i = 0; i < ARRAY_SIZE(p->supply); i++) {
		ret = regulator_set_voltage(supply[i].consumer, voltage[i], voltage[i]);
		if (ret)
			goto power_down;
		voted++;
		ret = regulator_enable(supply[i].consumer);
		if (ret)
			goto power_down;
		enabled++;
		p->raised |= 1 << i;
		/* Programmed regulator readback, not an analog voltage measurement. */
		p->rail_uv[i] = regulator_get_voltage(supply[i].consumer);
		p->voltage_read |= 1 << i;
		if (p->rail_uv[i] != voltage[i]) {
			ret = p->rail_uv[i] < 0 ? p->rail_uv[i] : -EIO;
			goto power_down;
		}
	}
	p->stage = "settle";
	usleep_range(3000, 6000);
	/* Shared supplies power BOTH emitters. Disable BOTH, even if one fails. */
	p->stage = "enable-off";
	ret = 0;
	for (i = 0; i < ARRAY_SIZE(emitters); i++) {
		cleanup = coral_off_disable(emitters[i], &p->enable[i]);
		if (cleanup)
			ret = cleanup;
		else
			p->off_verified |= 1 << i;
	}
	if (ret)
		goto power_down;
	p->stage = "ids-flags";
	for (i = 0; i < ARRAY_SIZE(emitters); i++) {
		ret = coral_off_read(emitters[i], LM3601X_DEV_ID_REG, &p->id[i]);
		if (!ret)
			p->id_read |= 1 << i;
		if (ret || p->id[i] != 1) {
			ret = ret ?: -ENODEV;
			goto power_down;
		}
		ret = coral_off_read(emitters[i], LM3601X_FLAGS_REG, &p->flags[i]);
		if (!ret)
			p->flags_read |= 1 << i;
		if (ret || p->flags[i]) {
			ret = ret ?: -EIO;
			goto power_down;
		}
	}
	p->stage = "silego-map";
	for (i = 0; i < ARRAY_SIZE(coral_silego_registers); i++) {
		ret = coral_off_read(silego, coral_silego_registers[i], &p->map[i]);
		if (!ret)
			p->map_read++;
		if (ret || p->map[i] != coral_silego_values[i]) {
			ret = ret ?: -EINVAL;
			goto power_down;
		}
	}
	p->stage = "f7";
	ret = coral_off_read(silego, 0xf7, &p->fault_flag);
	p->f7_read = !ret;
	if (ret || p->fault_flag != 0xc0) {
		ret = ret ?: -EIO;
		goto power_down;
	}
	p->stage = "fault-gpio";
	p->fault_gpio = gpiod_get_value_cansleep(fault);
	ret = p->fault_gpio;
	if (ret)
		ret = ret < 0 ? ret : -EIO;
	else
		p->stage = "checks-complete";
power_down:
	/* Attempt OFF on both even after any timeout/read/voltage error. */
	if (enabled >= 3)
		for (i = 0; i < ARRAY_SIZE(emitters); i++) {
			p->off_verified &= ~(1 << i);
			cleanup = coral_off_disable(emitters[i], &p->enable[i]);
			if (cleanup) {
				dev_err(dev, "OFF unverified for emitter %d: %d\n", i, cleanup);
				ret = cleanup;
			} else
				p->off_verified |= 1 << i;
		}
	while (voted) {
		i = --voted;
		if (i < enabled) {
			cleanup = regulator_disable(supply[i].consumer);
			if (cleanup) {
				dev_err(dev, "rail %d disable failed: %d\n", i, cleanup);
				ret = cleanup;
				continue; /* Preserve vote if hardware disable failed. */
			}
			p->disabled |= 1 << i;
		}
		cleanup = regulator_set_voltage(supply[i].consumer, 0, voltage[i]);
		if (cleanup) {
			dev_err(dev, "rail %d vote release failed: %d\n", i, cleanup);
			ret = cleanup;
		} else
			p->released |= 1 << i;
	}
	mutex_unlock(&coral_off_mutex);
	if (ret)
		dev_err(dev, "power/OFF diagnostic failed: %d; emission inhibited\n", ret);
	/* Retain regulator handles/votes on failure; the read-only result is the
	 * verdict. A successful driver bind alone never establishes verified OFF.
	 */
	p->verified = !ret;
	p->error = ret;
	if (!ret)
		dev_info(dev, "both ids=01 ENABLE=00; ver4/F7=c0; lock/optical envelope unverified; ON inhibited\n");
	/* Bind to retain failed-cleanup votes; result.error carries the verdict. */
	ret = 0;
put_silego:
	put_device(&silego->dev);
put_peer:
	put_device(&emitters[1]->dev);
	return ret;
}
