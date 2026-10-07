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
    float value = clamp(dot(texture(source, qt_TexCoord0), ubuf.channelSelector), 0.0, 1.0);
    // Transparent semantic draws carry premultiplied white coverage. RGB and
    // alpha both remain `value`, so sampling this intermediate again cannot
    // square or fourth-power attenuate an edge.
    fragColor = (ubuf.outputAlpha > 0.5
        ? vec4(vec3(value), value)
        : vec4(vec3(value), 1.0)) * ubuf.qt_Opacity;
}

