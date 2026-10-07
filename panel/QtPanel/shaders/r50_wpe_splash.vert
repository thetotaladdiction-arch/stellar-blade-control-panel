#version 440

layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 qt_TexCoord0;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float age;
    float lifetime;
    float strength;
    float eventSeed;
    float roleCode;
    vec2 splashCenter;
    vec2 splashExtent;
    vec2 viewportSize;
    vec2 atlasSize;
    vec4 jet0;
    vec4 jet1;
    vec4 jet2;
    vec4 jet3;
    vec4 jet4;
    vec4 jet5;
    vec4 jet6;
} ubuf;

void main()
{
    qt_TexCoord0 = qt_MultiTexCoord0;
    gl_Position = ubuf.qt_Matrix * qt_Vertex;
}
