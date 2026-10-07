#version 440

layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 qt_TexCoord0;

// Keep this block byte-for-byte identical to r50_wpe_contact_ripple.frag.
// Qt Quick shares binding 0 between both stages on every RHI backend.
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 viewportSize;
    float rippleDisplacementPixels;
    float contactRippleEnabled;
    float sceneTime;
    float waterRippleSpeed;
    vec4 ripple0;
    vec4 ripple1;
    vec4 ripple2;
    vec4 ripple3;
    vec4 ripple4;
    vec4 ripple5;
    vec4 ripple6;
    vec4 ripple7;
    float rippleRingCount0;
    float rippleRingCount1;
    float rippleRingCount2;
    float rippleRingCount3;
    float rippleRingCount4;
    float rippleRingCount5;
    float rippleRingCount6;
    float rippleRingCount7;
} ubuf;

void main()
{
    qt_TexCoord0 = qt_MultiTexCoord0;
    gl_Position = ubuf.qt_Matrix * qt_Vertex;
}
