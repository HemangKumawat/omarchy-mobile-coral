/* SPDX-License-Identifier: GPL-2.0-only */
/* Coral: AP-clocked 48 kHz, four 32-bit DSP_A slots on TERT/QUAT. */
#include <linux/clk.h>
#define CORAL_TDM_BCLK 6144000
#define CORAL_DIGITAL_MAX 608 /* -26 dB; speaker-protection DSP is absent. */

static bool sm8150_is_coral(struct snd_soc_card *card)
{
	return of_machine_is_compatible("google,coral");
}

static bool sm8150_coral_port(struct snd_soc_card *card, int id)
{
	return sm8150_is_coral(card) &&
		(id == TERTIARY_TDM_RX_0 || id == QUATERNARY_TDM_TX_0);
}

static int sm8150_coral_fixup(struct snd_soc_pcm_runtime *rtd,
			     struct snd_pcm_hw_params *params)
{
	struct snd_interval *rate = hw_param_interval(params, SNDRV_PCM_HW_PARAM_RATE);
	struct snd_interval *channels = hw_param_interval(params, SNDRV_PCM_HW_PARAM_CHANNELS);
	struct snd_mask *fmt = hw_param_mask(params, SNDRV_PCM_HW_PARAM_FORMAT);

	rate->min = rate->max = 48000;
	channels->min = channels->max =
		snd_soc_rtd_to_cpu(rtd, 0)->id == QUATERNARY_TDM_TX_0 ? 4 : 2;
	snd_mask_none(fmt);
	snd_mask_set_format(fmt, SNDRV_PCM_FORMAT_S32_LE);
	return 0;
}

static int sm8150_coral_hw_params(struct snd_pcm_substream *substream,
				struct snd_pcm_hw_params *params)
{
	struct snd_soc_pcm_runtime *rtd = snd_soc_substream_to_rtd(substream);
	struct snd_soc_dai *cpu = snd_soc_rtd_to_cpu(rtd, 0), *codec;
	unsigned int offsets[] = { 0, 4, 8, 12 };
	bool capture = substream->stream == SNDRV_PCM_STREAM_CAPTURE;
	int channels = capture ? 4 : 2, ret, i;

	if (params_rate(params) != 48000 || params_channels(params) != channels ||
	    params_format(params) != SNDRV_PCM_FORMAT_S32_LE)
		return -EINVAL;
	ret = snd_soc_dai_set_tdm_slot(cpu, capture ? 0xf : 0,
				     capture ? 0 : 3, 4, 32);
	if (ret < 0)
		return ret;
	ret = snd_soc_dai_set_channel_map(cpu, capture ? channels : 0,
			capture ? offsets : NULL, capture ? 0 : channels,
			capture ? NULL : offsets);
	if (ret < 0 || capture)
		return ret;
	for_each_rtd_codec_dais(rtd, i, codec) {
		ret = snd_soc_dai_set_sysclk(codec, 0, CORAL_TDM_BCLK, SND_SOC_CLOCK_IN);
		if (ret < 0)
			return ret;
		ret = snd_soc_component_set_sysclk(codec->component, 0, 0,
						   CORAL_TDM_BCLK, SND_SOC_CLOCK_IN);
		if (ret < 0)
			return ret;
	}
	return 0;
}

static int sm8150_coral_startup(struct snd_pcm_substream *substream)
{
	struct snd_soc_pcm_runtime *rtd = snd_soc_substream_to_rtd(substream);
	struct snd_soc_dai *cpu = snd_soc_rtd_to_cpu(rtd, 0), *codec;
	int ret, i, clock = cpu->id == TERTIARY_TDM_RX_0 ?
		Q6AFE_LPASS_CLK_ID_TER_TDM_IBIT : Q6AFE_LPASS_CLK_ID_QUAD_TDM_IBIT;

	if (substream->stream == SNDRV_PCM_STREAM_PLAYBACK) {
		for_each_rtd_codec_dais(rtd, i, codec) {
			ret = snd_soc_dai_set_fmt(codec, SND_SOC_DAIFMT_CBC_CFC |
						 SND_SOC_DAIFMT_NB_NF | SND_SOC_DAIFMT_DSP_A);
			if (ret < 0)
				return ret;
		}
	}
	return snd_soc_dai_set_sysclk(cpu, clock, CORAL_TDM_BCLK, substream->stream);
}

static void sm8150_coral_shutdown(struct snd_pcm_substream *substream)
{
	struct snd_soc_pcm_runtime *rtd = snd_soc_substream_to_rtd(substream);
	struct snd_soc_dai *cpu = snd_soc_rtd_to_cpu(rtd, 0);
	int ret, clock = cpu->id == TERTIARY_TDM_RX_0 ?
		Q6AFE_LPASS_CLK_ID_TER_TDM_IBIT : Q6AFE_LPASS_CLK_ID_QUAD_TDM_IBIT;

	ret = snd_soc_dai_set_sysclk(cpu, clock, 0, substream->stream);
	if (ret < 0)
		dev_err(rtd->dev, "Coral TDM clock stop failed: %d\n", ret);
}

static int sm8150_coral_late_probe(struct snd_soc_card *card)
{
	static const char * const names[] = {
		"Top Digital PCM Volume", "Bottom Digital PCM Volume",
		"Top Analog PCM Volume", "Bottom Analog PCM Volume",
	};
	struct snd_ctl_elem_value *value;
	struct snd_kcontrol *control;
	struct soc_mixer_control *mixer;
	struct clk *clock;
	int i, ret;

	if (!sm8150_is_coral(card))
		return 0;
	clock = devm_clk_get_enabled(card->dev, "iaxxx");
	if (IS_ERR(clock))
		return dev_err_probe(card->dev, PTR_ERR(clock), "IA8508 reference clock\n");
	value = devm_kzalloc(card->dev, sizeof(*value), GFP_KERNEL);
	if (!value)
		return -ENOMEM;
	for (i = 0; i < ARRAY_SIZE(names); i++) {
		control = snd_soc_card_get_kcontrol(card, names[i]);
		if (!control)
			return dev_err_probe(card->dev, -EINVAL, "Missing %s\n", names[i]);
		/* Do not mutate the codec driver's static shared mixer descriptors. */
		mixer = devm_kmemdup(card->dev, (void *)control->private_value,
				    sizeof(*mixer), GFP_KERNEL);
		if (!mixer)
			return -ENOMEM;
		control->private_value = (unsigned long)mixer;
		value->value.integer.value[0] = i < 2 ? CORAL_DIGITAL_MAX : 0;
		if (i < 2)
			mixer->platform_max = CORAL_DIGITAL_MAX;
		ret = control->put(control, value);
		if (ret < 0)
			return dev_err_probe(card->dev, ret, "Cannot cap %s\n", names[i]);
		/* ALSA's platform_max=0 means unlimited, so freeze analogue at zero. */
		if (i >= 2)
			control->vd[0].access &= ~SNDRV_CTL_ELEM_ACCESS_WRITE;
	}
	return 0;
}
