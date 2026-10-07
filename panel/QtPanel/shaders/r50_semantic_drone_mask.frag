#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 channelSelector;
    float outputAlpha;
} ubuf;

layout(binding = 1) uniform sampler2D source;

void main()
{
    vec2 texel = vec2(1.0 / 960.0, 1.0 / 540.0);
    float coverage = 0.0;
    for (int y = -1; y <= 1; ++y) {
        for (int x = -1; x <= 1; ++x) {
            vec2 uv = clamp(qt_TexCoord0 + vec2(x, y) * texel,
                            vec2(0.0), vec2(1.0));
            coverage = max(coverage, dot(texture(source, uv), ubuf.channelSelector));
        }
    }
    coverage = clamp(coverage, 0.0, 1.0);
    fragColor = vec4(vec3(coverage), coverage) * ubuf.qt_Opacity;
}

