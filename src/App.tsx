import { useState, useEffect } from 'react';
import { Tag, Users, Star, ExternalLink } from 'lucide-react';

interface Course {
  title: string;
  url: string;
  original_price: string;
  discount_price: string;
  rating: number | string;
  students: string;
  category: string;
  coupon_code: string;
  platform: string;
}

const MOCK_COURSES: Course[] = [
  {
    title: "100 Days of Code: The Complete Python Pro Bootcamp",
    url: "#",
    original_price: "$89.99",
    discount_price: "Free",
    rating: 4.7,
    students: "1,200,450",
    category: "programming",
    coupon_code: "FREE2026",
    platform: "Udemy"
  },
  {
    title: "Complete Web Design: from Figma to Webflow",
    url: "#",
    original_price: "$119.99",
    discount_price: "Free",
    rating: 4.8,
    students: "45,200",
    category: "design",
    coupon_code: "DESIGN100",
    platform: "Udemy"
  },
  {
    title: "Machine Learning A-Z: AI, Python & R",
    url: "#",
    original_price: "$94.99",
    discount_price: "Free",
    rating: 4.5,
    students: "850,000",
    category: "data",
    coupon_code: "DATA_AI_FREE",
    platform: "Udemy"
  }
];

export default function App() {
  const [courses, setCourses] = useState<Course[]>(MOCK_COURSES);

  return (
    <div className="min-h-screen bg-[#f5f5f7] text-gray-900 font-sans selection:bg-blue-200">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-30 shadow-sm">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-blue-600 text-white rounded-lg flex items-center justify-center font-bold font-serif italic text-xl">
              U
            </div>
            <h1 className="font-semibold text-lg tracking-tight">UdemyFree Drops</h1>
          </div>
          <div className="text-sm font-medium text-gray-500 bg-gray-100 px-3 py-1 rounded-full">
            {courses.length} Courses Found
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-12 pb-24">
        <div className="mb-10 text-center">
          <h2 className="text-4xl font-light tracking-tight mb-3">Today's Free Courses</h2>
          <p className="text-gray-500">Curated daily drops with 100% off coupons applied automatically.</p>
        </div>

        <div className="grid gap-6">
          {courses.map((course, index) => (
            <div key={index} className="bg-white rounded-2xl p-6 shadow-[0_2px_12px_rgba(0,0,0,0.04)] border border-gray-100 flex flex-col md:flex-row gap-6 items-start md:items-center hover:shadow-[0_8px_24px_rgba(0,0,0,0.06)] transition-all cursor-default group relative overflow-hidden">
              
              {/* Highlight bar on hover */}
              <div className="absolute left-0 top-0 bottom-0 w-1 bg-blue-600 translate-x-[-100%] group-hover:translate-x-0 transition-transform"></div>

              <div className="flex-1 space-y-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="bg-blue-50 text-blue-600 text-[10px] sm:text-xs font-semibold px-2.5 py-1 rounded-full uppercase tracking-wider">
                    {course.category}
                  </span>
                  <span className="text-emerald-600 font-medium text-sm flex items-center gap-1 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-100">
                    {course.discount_price} <span className="text-emerald-800/40 line-through text-xs font-normal ml-1">{course.original_price}</span>
                  </span>
                </div>
                
                <h3 className="text-lg md:text-xl font-medium tracking-tight text-gray-900 leading-snug">
                  {course.title}
                </h3>
                
                <div className="flex flex-wrap items-center gap-4 text-sm text-gray-500">
                  <div className="flex items-center gap-1">
                    <Star size={14} className="text-amber-400" fill="currentColor" />
                    <span className="font-medium text-gray-700">{course.rating}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Users size={14} />
                    <span>{course.students} students</span>
                  </div>
                  <div className="flex items-center gap-1" title="Coupon Code">
                    <Tag size={14} />
                    <span className="font-mono text-xs font-medium text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">{course.coupon_code}</span>
                  </div>
                </div>
              </div>

              <div className="w-full md:w-auto shrink-0 pt-4 md:pt-0 border-t md:border-none border-gray-100">
                <a 
                  href={course.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="w-full md:w-auto inline-flex items-center justify-center gap-2 bg-gray-900 text-white rounded-xl px-6 py-3 text-sm font-medium hover:bg-blue-600 transition-colors shadow-sm focus:ring-2 focus:ring-offset-2 focus:ring-gray-900"
                >
                  Enroll Now
                  <ExternalLink size={16} />
                </a>
              </div>
            </div>
          ))}
        </div>
        
        {courses.length === 0 && (
          <div className="text-center py-20 bg-white rounded-2xl border border-gray-200 border-dashed">
            <p className="text-gray-500">No courses available. Run the scraper to populate data.</p>
          </div>
        )}
      </main>
    </div>
  );
}
