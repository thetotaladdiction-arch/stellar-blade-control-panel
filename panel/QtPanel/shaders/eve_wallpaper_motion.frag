#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float phase;
    float intensity;
    float clipOriginX;
    float clipOriginY;
    float clipScaleX;
    float clipScaleY;
} ubuf;

layout(binding = 1) uniform sampler2D source;
layout(binding = 2) uniform sampler2D motionMask;

const float TAU = 6.28318530718;

void main()
{
    vec2 screenUv = qt_TexCoord0;
    vec2 uv = vec2(
        ubuf.clipOriginX + screenUv.x * ubuf.clipScaleX,
        ubuf.clipOriginY + screenUv.y * ubuf.clipScaleY
    );
    vec3 mask = texture(motionMask, uv).rgb;
    float hair = mask.r;
    float suitLight = mask.g;
    float warmAmbience = mask.b;
    float t = ubuf.phase * TAU;

    // The official 4K frame stays complete. Only the long trailing ponytail
    // receives a few pixels of feathered secondary motion; face and body
    // geometry are black in the displacement mask and remain exact.
    vec2 offset = vec2(0.0);
    offset.x += hair
        * (sin(t * 0.64 + uv.y * 17.0)
           + 0.48 * sin(t * 0.37 + uv.y * 8.0))
        * 0.00062;
    offset.y += hair
        * cos(t * 0.51 + uv.x * 12.0)
        * 0.00022;

    vec4 color = texture(source, clamp(uv + offset * ubuf.intensity, 0.0, 1.0));

    // Existing suit technology and distant warm rock light breathe at
    // independent, slow rates. These are additive responses on top of the
    // original pixels, not replacement textures or global recoloring.
    float suitPulse = 0.5 + 0.5 * sin(t * 0.43);
    float suitSweep = pow(max(0.0, sin(t * 0.19 - uv.y * 4.5)), 8.0);
    color.rgb += vec3(0.015, 0.050, 0.070)
        * suitLight
        * (0.22 * suitPulse + 0.34 * suitSweep)
        * ubuf.intensity;

    float warmPulse = 0.5 + 0.5 * sin(t * 0.21 + 1.2);
    color.rgb += vec3(0.040, 0.012, 0.004)
        * warmAmbience
        * warmPulse
        * ubuf.intensity;

    fragColor = color * ubuf.qt_Opacity;
}
