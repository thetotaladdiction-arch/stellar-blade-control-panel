#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float lightPulse;
} ubuf;

layout(binding = 1) uniform sampler2D source;

void main()
{
    vec4 color = texture(source, qt_TexCoord0);
    float blueAuthority = smoothstep(
        0.025,
        0.28,
        color.b - max(color.r, color.g) * 0.72
    ) * color.a;
    color.rgb += vec3(0.10, 0.64, 1.0)
                 * blueAuthority * clamp(ubuf.lightPulse, 0.0, 0.18) * 1.8;
    fragColor = color * ubuf.qt_Opacity;
}
