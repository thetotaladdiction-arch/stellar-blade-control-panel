#version 440

layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 qt_TexCoord0;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 rigSize;
    vec2 wristOffset;
    vec2 clothOffset;
    float shoulderFollow;
    float cuffFollow;
    float gloveFollow;
} ubuf;

layout(binding = 2) uniform sampler2D weights;
layout(binding = 3) uniform sampler2D clothTipWeight;

void main()
{
    qt_TexCoord0 = qt_MultiTexCoord0;

    vec3 regionWeight = texture(weights, qt_MultiTexCoord0).rgb;
    float clothTipInfluence = texture(clothTipWeight, qt_MultiTexCoord0).r;
    float follow = dot(
        regionWeight,
        vec3(ubuf.shoulderFollow, ubuf.cuffFollow, ubuf.gloveFollow)
    );

    vec4 displaced = qt_Vertex;
    displaced.xy += ubuf.wristOffset * ubuf.rigSize * follow;
    displaced.xy += ubuf.clothOffset * ubuf.rigSize * clothTipInfluence;
    gl_Position = ubuf.qt_Matrix * displaced;
}
